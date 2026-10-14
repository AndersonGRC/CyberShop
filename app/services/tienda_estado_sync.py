"""Lo que una tienda autoservicio muestra de su plan, escrito desde el motor de
venta (la instancia de CyberShop) en el `cliente_config` de la tienda:

- en prueba: `trial_hasta` y `trial_renovar_url` (el aviso «te quedan N días»);
- prueba vencida sin pagar: `trial_pausada` y `trial_eliminar_desde` (la tienda
  queda en pausa: los visitantes ven un aviso y el dueño, cómo activar su plan);
- plan pagado: se borran las claves de la prueba y queda `plan_renovar_url`;
- siempre: `soporte_whatsapp` y `soporte_email` del operador (ayuda en la tienda).

Solo toca tiendas con `tienda_autoservicio='true'` (las que crea la página de
CyberShop); a las demás no se les escribe nada. Se llama al crear la tienda, al
convertir la prueba y cada día desde el cron de cobros, así un pago manual o una
prórroga del maestro también se ven en la tienda. Nunca rompe a quien la llama.
"""

import re
from datetime import timedelta

BASE_URL = 'https://cybershopcol.com'
CLAVES_PRUEBA = ('trial_hasta', 'trial_renovar_url', 'trial_pausada', 'trial_eliminar_desde')
# Días que se guarda una prueba pausada antes de que el operador pueda borrarla.
RETENCION_PRUEBA_DIAS = 30


def eliminar_desde(compra):
    """Fecha desde la que se podría borrar una prueba que terminó sin pagar."""
    if not compra or not compra.get('proximo_pago'):
        return None
    return compra['proximo_pago'] + timedelta(days=1 + RETENCION_PRUEBA_DIAS)


def renovar_url(compra):
    token = (compra or {}).get('token_renovacion')
    return f"{BASE_URL}/renovar/{token}" if token else ''


def valores_para(compra):
    """(claves a escribir, claves a borrar) en la tienda según su compra."""
    escribir, borrar = {}, []
    url = renovar_url(compra)
    if compra.get('es_trial'):
        if compra.get('proximo_pago'):
            escribir['trial_hasta'] = str(compra['proximo_pago'])
        if url:
            escribir['trial_renovar_url'] = url
        if compra.get('suspendida_por_pago'):
            escribir['trial_pausada'] = 'true'
            fecha = eliminar_desde(compra)
            if fecha:
                escribir['trial_eliminar_desde'] = str(fecha)
        else:
            borrar += ['trial_pausada', 'trial_eliminar_desde']
    else:
        borrar += list(CLAVES_PRUEBA)
        if url:
            escribir['plan_renovar_url'] = url
    return escribir, borrar


def soporte_operador():
    """WhatsApp (solo dígitos) y correo del operador, de su propio cliente_config."""
    try:
        from helpers_email_templates import _get_empresa_info
        info = _get_empresa_info()
    except Exception:  # noqa: BLE001
        return {}
    whatsapp = re.sub(r'\D', '', str(info.get('whatsapp') or info.get('telefono') or ''))
    if len(whatsapp) == 10:
        whatsapp = '57' + whatsapp
    return {'soporte_whatsapp': whatsapp, 'soporte_email': (info.get('email') or '').strip()}


def sincronizar(compra):
    """Escribe en la BD de la tienda lo que corresponde a su compra. True si
    escribió; False si no aplica (no está activada, no es autoservicio) o falló."""
    if not compra or not compra.get('tenant_id') or compra.get('estado') != 'ACTIVADA':
        return False
    try:
        from services.db_layer import tenant_cursor
        from services.config_tenant import set_cliente_config
        from services.venta_automatica_service import _db_del_tenant
        escribir, borrar = valores_para(compra)
        escribir.update({k: v for k, v in soporte_operador().items() if v})
        with tenant_cursor(db_name=_db_del_tenant(compra['tenant_id'])) as cur:
            cur.execute("SELECT valor FROM cliente_config WHERE clave = 'tienda_autoservicio' LIMIT 1")
            fila = cur.fetchone()
            if not fila or str(fila[0]).strip().lower() != 'true':
                return False
            for clave, valor in escribir.items():
                set_cliente_config(cur, clave, valor, descripcion='Plan de la tienda (automático)')
            if borrar:
                cur.execute("DELETE FROM cliente_config WHERE clave = ANY(%s)", (list(borrar),))
        return True
    except Exception as exc:  # noqa: BLE001 — la tienda sigue funcionando; se reintenta mañana
        try:
            from flask import current_app
            current_app.logger.warning(f"sincronizar tienda {compra.get('tenant_id')}: {exc}")
        except Exception:  # noqa: BLE001
            print(f"  [!] sincronizar tienda {compra.get('tenant_id')}: {exc}")
        return False
