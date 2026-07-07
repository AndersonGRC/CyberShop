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
                "SELECT tenant_id, proxima_fecha FROM tenant_billing "
                "WHERE tenant_id = ANY(%s) AND proxima_fecha IS NOT NULL",
                ([c['tenant_id'] for c in con_tenant],),
            )
            panel = {int(r['tenant_id']): r['proxima_fecha'] for r in cur.fetchall()}
        ajustes = 0
        for c in con_tenant:
            fecha_panel = panel.get(int(c['tenant_id']))
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
    from helpers_email_templates import (
        generar_email_recordatorio_pago, generar_email_aviso_operador,
        generar_email_trial_recordatorio)

    hoy = date.today()
    auto_dias = int(getattr(Config, 'AUTO_SUSPENDER_DIAS', 0) or 0)
    operador = Config.MAIL_USERNAME
    compras = pcs.compras_para_recordatorio()
    print(f"[{hoy}] {len(compras)} compras activas con fecha de cobro "
          f"(auto-suspensión: {'OFF' if auto_dias == 0 else f'{auto_dias} días'})")
    _sincronizar_desde_panel(compras)

    resumen_vencidos = []
    for c in compras:
        dias = (c['proximo_pago'] - hoy).days   # >0 faltan; <0 vencido
        plan = get_plan(c['plan_key']) or {'nombre': c['plan_key']}
        url = f"{BASE_URL}/renovar/{c['token_renovacion']}" if c['token_renovacion'] else BASE_URL
        etapa_previa = c.get('ultimo_recordatorio') or ''

        # ── PRUEBA GRATIS (15 días): avisos día 10/13/15, suspensión día 16 ──
        if c.get('es_trial'):
            if dias <= -1 and not c['suspendida_por_pago']:
                print(f"  [TRIAL-SUSPENDER] {c['dominio']} (venció hace {-dias}d)")
                try:
                    from services.master_client import suspender_tenant
                    if c['tenant_id']:
                        suspender_tenant(c['tenant_id'])
                    pcs.marcar_suspendida_por_pago(c['id'])
                    pcs.marcar_recordatorio(c['id'], 'trial_fin')
                    _enviar(c['buyer_email'], generar_email_trial_recordatorio(
                        c, plan, url, 0))
                    _enviar(operador, generar_email_aviso_operador(
                        f"⏸️ Prueba gratis vencida sin pago — {c['dominio']}",
                        [f"Cliente: {c['buyer_nombre']} <{c['buyer_email']}> "
                         f"{('Tel: ' + c['buyer_telefono']) if c.get('buyer_telefono') else ''}",
                         "La tienda quedó pausada; se reactiva sola si paga."]))
                except Exception as exc:  # noqa: BLE001
                    print(f"  [!] suspensión de trial falló: {exc}")
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

        # ── Suspensión automática (opcional) ──
        if auto_dias > 0 and dias <= -auto_dias and not c['suspendida_por_pago']:
            print(f"  [SUSPENDER] {c['dominio']} ({-dias} días vencido)")
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
    print("Listo.")


if __name__ == '__main__':
    with app.app_context():
        main()
