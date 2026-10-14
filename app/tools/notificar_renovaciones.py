"""Cron diario de cobro recurrente: recordatorios de renovación y (opcional)
suspensión automática por no-pago.

Se ejecuta una vez al día (cron del servidor, ej. 8:00am):
    cd /var/www/CyberShop/app && env/bin/python tools/notificar_renovaciones.py

Etapas según `proximo_pago` vs hoy (sin duplicados vía ultimo_recordatorio):
  - 'previo'  : faltan 1-5 días  → email al cliente con link de renovación.
  - 'dia0'    : vence hoy        → email al cliente.
  - 'vencido' : 3+ días vencido  → email urgente al cliente + aviso al operador.
  - suspensión: si AUTO_SUSPENDER_DIAS > 0 y lleva >= N días vencido →
                suspende la instancia vía maestro + emails. Con 0 (default),
                solo se notifica y la suspensión queda en manos del operador.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app  # noqa: E402  (crea el Flask app con su config)


BASE_URL = 'https://cybershopcol.com'


def _enviar(destino, email_tuple):
    if not email_tuple or not destino:
        return False
    try:
        from helpers_gmail import enviar_email_gmail
        asunto, texto, html = email_tuple
        return enviar_email_gmail(destino, asunto, texto, html=html)
    except Exception as exc:  # noqa: BLE001
        print(f"  [!] email a {destino} falló: {exc}")
        return False


def _sincronizar_desde_panel(compras):
    """Puente panel→motor: si el operador registró un pago manual en fADMIN
    (tenant_billing.proxima_fecha avanzó más allá de plan_compras.proximo_pago),
    el motor adopta la fecha del panel y limpia recordatorios/suspensión.
    Una sola dirección; nunca atrasa fechas."""
    try:
        from services.db_layer import control_plane_cursor
        from services import plan_compras_service as pcs
        from database import get_db_cursor
        con_tenant = [c for c in compras if c.get('tenant_id')]
        if not con_tenant:
            return 0
        with control_plane_cursor(dict_cursor=True) as cur:
            cur.execute(
                "SELECT tenant_id, proxima_fecha, dias_suspension, auto_suspender "
                "FROM tenant_billing WHERE tenant_id = ANY(%s)",
                ([c['tenant_id'] for c in con_tenant],),
            )
            panel = {int(r['tenant_id']): r for r in cur.fetchall()}
        ajustes = 0
        for c in con_tenant:
            fila = panel.get(int(c['tenant_id']))
            # Plazo de suspensión y switch, POR CLIENTE (los fija el operador en fADMIN).
            if fila is not None:
                c['dias_suspension_cfg'] = fila.get('dias_suspension')
                c['auto_suspender_cfg'] = fila.get('auto_suspender')
            fecha_panel = fila['proxima_fecha'] if fila else None
            if fecha_panel and c['proximo_pago'] and fecha_panel > c['proximo_pago']:
                with get_db_cursor() as cur:
                    cur.execute(
                        """
                        UPDATE plan_compras
                        SET proximo_pago = %s, ultimo_recordatorio = NULL,
                            suspendida_por_pago = FALSE, es_trial = FALSE
                        WHERE id = %s
                        """,
                        (fecha_panel, c['id']),
                    )
                c['proximo_pago'] = fecha_panel
                c['ultimo_recordatorio'] = None
                c['suspendida_por_pago'] = False
                c['es_trial'] = False
                ajustes += 1
                print(f"  [PANEL→MOTOR] tenant {c['tenant_id']}: próximo pago {fecha_panel}")
        return ajustes
    except Exception as exc:  # noqa: BLE001 — el puente nunca rompe el cron
        print(f"  [!] puente panel→motor falló: {exc}")
        return 0


def main():
    from config import Config
    from services import plan_compras_service as pcs
    from services.software_planes_service import get_plan
    from services.tienda_estado_sync import sincronizar, eliminar_desde
    from services.venta_automatica_service import avisar_falla_creacion
    from helpers_email_templates import (
        generar_email_recordatorio_pago, generar_email_aviso_operador,
        generar_email_trial_recordatorio, generar_email_trial_pausada)

    # Tiendas cuya creación quedó a medias (p. ej. un reinicio mató el hilo):
    # pasan a ERROR para poder reintentar y el operador se entera.
    for compra_id in pcs.compras_atascadas():
        fila = pcs.marcar_atascada(compra_id)
        if fila:
            print(f"  [ATASCADA] compra {compra_id} ({fila.get('slug')}) → ERROR")
            avisar_falla_creacion(fila, fila.get('slug'), fila.get('error'))

    hoy = date.today()
    # AUTO_SUSPENDER_DIAS actúa como INTERRUPTOR MAESTRO (>0 = auto-suspensión ON).
    # El PLAZO en días lo decide el operador POR CLIENTE (tenant_billing.dias_suspension);
    # si no lo fijó, se usa DEFAULT_GRACE.
    master_on = int(getattr(Config, 'AUTO_SUSPENDER_DIAS', 0) or 0) > 0
    DEFAULT_GRACE = 30
    operador = Config.MAIL_USERNAME
    # dict() por fila: las filas de RealDictCursor NO admiten claves nuevas
    # (RealDictRow lanza KeyError al asignar), y el puente panel→motor agrega
    # 'dias_suspension_cfg'/'auto_suspender_cfg'. Convertir evita romper el puente.
    compras = [dict(c) for c in pcs.compras_para_recordatorio()]
    print(f"[{hoy}] {len(compras)} compras activas con fecha de cobro "
          f"(auto-suspensión: {'OFF' if not master_on else f'ON, plazo por cliente (default {DEFAULT_GRACE}d)'})")
    _sincronizar_desde_panel(compras)

    resumen_vencidos = []
    for c in compras:
        dias = (c['proximo_pago'] - hoy).days   # >0 faltan; <0 vencido
        plan = get_plan(c['plan_key']) or {'nombre': c['plan_key']}
        url = f"{BASE_URL}/renovar/{c['token_renovacion']}" if c['token_renovacion'] else BASE_URL
        etapa_previa = c.get('ultimo_recordatorio') or ''

        # ── PRUEBA GRATIS (15 días): avisos día 10/13/15, pausa el día 16 ──
        if c.get('es_trial'):
            if dias >= 0 and c['suspendida_por_pago']:
                # El operador le dio más plazo a una prueba ya pausada: se reabre.
                if pcs.quitar_pausa(c['id']):
                    c['suspendida_por_pago'] = False
                    c['ultimo_recordatorio'] = etapa_previa = ''
                    print(f"  [TRIAL-REANUDA] {c['dominio']} (prueba hasta {c['proximo_pago']})")
            if dias <= -1 and not c['suspendida_por_pago']:
                # Pausa SUAVE: la tienda sigue encendida; los visitantes ven «en
                # pausa» y el dueño, cómo activar su plan (antes se apagaba la
                # instancia y todos veían un error 502). Se abre sola al pagar.
                print(f"  [TRIAL-PAUSA] {c['dominio']} (venció hace {-dias}d)")
                c['suspendida_por_pago'] = True
                if sincronizar(c):
                    pcs.marcar_suspendida_por_pago(c['id'])
                    pcs.marcar_recordatorio(c['id'], 'trial_fin')
                    hasta = eliminar_desde(c)
                    _enviar(c['buyer_email'], generar_email_trial_pausada(c, plan, url, hasta))
                    _enviar(operador, generar_email_aviso_operador(
                        f"⏸️ Prueba gratis terminó sin pago — {c['dominio']}",
                        [f"Cliente: {c['buyer_nombre']} <{c['buyer_email']}> "
                         f"{('Tel: ' + c['buyer_telefono']) if c.get('buyer_telefono') else ''}",
                         "La tienda quedó EN PAUSA (sigue encendida: los visitantes ven el aviso y el "
                         "dueño, cómo pagar). Se abre sola si paga.",
                         f"Le dijimos que sus datos se guardan hasta el {hasta:%d/%m/%Y}: "
                         "no la borres en /pruebas antes de esa fecha." if hasta else ""]))
                else:
                    c['suspendida_por_pago'] = False
                    print(f"  [!] no se pudo pausar {c['dominio']}: se reintenta mañana")
                    _enviar(operador, generar_email_aviso_operador(
                        f"⚠️ No se pudo pausar la prueba vencida — {c['dominio']}",
                        [f"Cliente: {c['buyer_nombre']} <{c['buyer_email']}>",
                         "No se pudo escribir la pausa en su base de datos; el cron lo reintenta mañana."]))
            elif not c['suspendida_por_pago']:
                etapa = None
                if dias == 0 and etapa_previa != 'trial15':
                    etapa = ('trial15', 0)
                elif 1 <= dias <= 2 and etapa_previa not in ('trial13', 'trial15'):
                    etapa = ('trial13', dias)
                elif 3 <= dias <= 5 and etapa_previa == '':
                    etapa = ('trial10', dias)
                if etapa:
                    print(f"  [{etapa[0].upper()}] {c['dominio']} -> {c['buyer_email']}")
                    _enviar(c['buyer_email'], generar_email_trial_recordatorio(
                        c, plan, url, etapa[1]))
                    pcs.marcar_recordatorio(c['id'], etapa[0])
            continue

        # ── Suspensión automática (plazo POR CLIENTE + switch por cliente) ──
        _g = c.get('dias_suspension_cfg')
        grace = int(_g) if _g else DEFAULT_GRACE
        _flag = c.get('auto_suspender_cfg')
        auto_susp_tenant = True if _flag is None else bool(_flag)
        if master_on and auto_susp_tenant and dias <= -grace and not c['suspendida_por_pago']:
            print(f"  [SUSPENDER] {c['dominio']} ({-dias} días vencido, plazo {grace}d)")
            try:
                from services.master_client import suspender_tenant
                if c['tenant_id']:
                    suspender_tenant(c['tenant_id'])
                pcs.marcar_suspendida_por_pago(c['id'])
                pcs.marcar_recordatorio(c['id'], 'suspendida')
                _enviar(c['buyer_email'], generar_email_recordatorio_pago(
                    c, plan, url, 'vencido', dias=-dias))
                _enviar(operador, generar_email_aviso_operador(
                    f"⛔ Tienda SUSPENDIDA por no-pago — {c['dominio']}",
                    [f"Cliente: {c['buyer_nombre']} <{c['buyer_email']}>",
                     f"Plan: {plan.get('nombre')} | Vencido hace {-dias} días",
                     "Se reactivará sola cuando pague la renovación."]))
            except Exception as exc:  # noqa: BLE001
                print(f"  [!] suspensión falló: {exc}")
            continue

        if c['suspendida_por_pago']:
            continue  # ya suspendida: no insistir cada día

        # ── Recordatorios (una vez por etapa) ──
        if dias < 0 and -dias >= 3 and etapa_previa != 'vencido':
            print(f"  [VENCIDO {-dias}d] {c['dominio']} -> {c['buyer_email']}")
            _enviar(c['buyer_email'], generar_email_recordatorio_pago(
                c, plan, url, 'vencido', dias=-dias))
            pcs.marcar_recordatorio(c['id'], 'vencido')
            resumen_vencidos.append(
                f"{c['dominio']} — {c['buyer_nombre']} <{c['buyer_email']}> "
                f"— {plan.get('nombre')} — vencido hace {-dias} días")
        elif dias <= 0 and dias > -3 and etapa_previa not in ('dia0', 'vencido'):
            print(f"  [DIA0] {c['dominio']} -> {c['buyer_email']}")
            _enviar(c['buyer_email'], generar_email_recordatorio_pago(c, plan, url, 'dia0'))
            pcs.marcar_recordatorio(c['id'], 'dia0')
        elif 0 < dias <= 5 and etapa_previa == '':
            print(f"  [PREVIO -{dias}d] {c['dominio']} -> {c['buyer_email']}")
            _enviar(c['buyer_email'], generar_email_recordatorio_pago(c, plan, url, 'previo'))
            pcs.marcar_recordatorio(c['id'], 'previo')

    if resumen_vencidos:
        _enviar(operador, generar_email_aviso_operador(
            f"⚠️ {len(resumen_vencidos)} plan(es) vencidos sin pagar",
            resumen_vencidos + ["", "Puedes suspenderlos desde admin.cybershopcol.com"]))

    # Cada tienda autoservicio refleja su estado real (aviso de prueba, pausa,
    # enlace de pago): así un pago manual o una prórroga del maestro también se
    # ve en la tienda. Las demás tiendas no se tocan (sincronizar lo revisa).
    sincronizadas = sum(1 for c in compras if sincronizar(c))
    print(f"  {sincronizadas} tienda(s) autoservicio sincronizadas")
    print("Listo.")


if __name__ == '__main__':
    with app.app_context():
        main()
