"""Las pruebas gratis en el CRM del operador (BD de CyberShop, la misma de
`plan_compras`).

- Al registrarse: contacto `lead` con su WhatsApp, correo y negocio (sin
  duplicar si el correo ya existe).
- Al activarse la tienda: una actividad «Prueba activada» y una tarea de
  seguimiento para el día 12 (antes de que venza).
- Para la pantalla «Pruebas gratis»: cada prueba con su estado en palabras
  simples y los días que le quedan.

Todo es aditivo: nunca borra contactos, tareas ni compras. Si el CRM no existe
en la BD (cliente sin el módulo), no hace nada.
"""
from datetime import date, timedelta

from database import get_db_cursor

ORIGEN = 'prueba_gratis'
ETIQUETA = 'prueba-gratis'
DIA_SEGUIMIENTO = 12                 # la tarea vence el día 12 de 15
TIPOS_NEGOCIO = {
    'tienda': 'Tienda / comercio',
    'restaurante': 'Restaurante / cafetería',
    'servicios': 'Servicios',
    'otro': 'Otro',
}


def _hay_crm(cur):
    cur.execute("SELECT to_regclass('crm_contactos') IS NOT NULL AS hay")
    return bool(cur.fetchone()['hay'])


def _sitio(slug):
    return f'https://{slug}.cybershopcol.com' if slug else None


def registrar_interesado(cur, *, nombre, email, telefono, negocio, slug, tipo_negocio=None):
    """Crea o completa el contacto de quien pidió la prueba. Usa el cursor de
    quien llama (misma transacción que el registro). Devuelve el id o None."""
    if not _hay_crm(cur):
        return None
    email = (email or '').strip().lower()
    nota = (f"Prueba gratis registrada el {date.today():%d/%m/%Y}. Negocio: {negocio}"
            + (f" ({TIPOS_NEGOCIO.get(tipo_negocio, tipo_negocio)})" if tipo_negocio else '')
            + (f". Dirección: {_sitio(slug)}" if slug else ''))
    cur.execute("""SELECT id, notas FROM crm_contactos
                   WHERE LOWER(email) = %s ORDER BY activo DESC, id LIMIT 1""", (email,))
    fila = cur.fetchone()
    if fila:
        cur.execute("""UPDATE crm_contactos
                       SET telefono = COALESCE(NULLIF(%s, ''), telefono),
                           whatsapp = COALESCE(NULLIF(%s, ''), whatsapp),
                           empresa = COALESCE(NULLIF(empresa, ''), %s),
                           sitio_web = COALESCE(NULLIF(sitio_web, ''), %s),
                           notas = CONCAT_WS(E'\\n', NULLIF(notas, ''), %s),
                           tags = CASE WHEN %s = ANY(COALESCE(tags, '{}')) THEN tags
                                       ELSE array_append(COALESCE(tags, '{}'), %s) END,
                           activo = TRUE,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = %s""",
                    (telefono, telefono, negocio, _sitio(slug), nota, ETIQUETA, ETIQUETA, fila['id']))
        return fila['id']
    cur.execute("""INSERT INTO crm_contactos
                       (tipo, nombre, empresa, email, telefono, whatsapp, sitio_web,
                        notas, origen, tags, activo)
                   VALUES ('lead', %s, %s, %s, %s, %s, %s, %s, %s, ARRAY[%s], TRUE)
                   RETURNING id""",
                (nombre or negocio or email, negocio, email, telefono or None, telefono or None,
                 _sitio(slug), nota, ORIGEN, ETIQUETA))
    return cur.fetchone()['id']


def prueba_activada(compra):
    """La tienda de prueba quedó lista: actividad + tarea de seguimiento.
    Idempotente (no repite la tarea si ya existe). Nunca lanza."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            if not _hay_crm(cur):
                return None
            cid = registrar_interesado(
                cur, nombre=compra.get('buyer_nombre'), email=compra.get('buyer_email'),
                telefono=compra.get('buyer_telefono') or '', negocio=compra.get('nombre_negocio'),
                slug=compra.get('slug'), tipo_negocio=compra.get('tipo_negocio'))
            dominio = compra.get('dominio') or _sitio(compra.get('slug')) or ''
            vence = compra.get('proximo_pago')
            cur.execute("""INSERT INTO crm_actividades (contacto_id, tipo, asunto, descripcion)
                           VALUES (%s, 'nota', %s, %s)""",
                        (cid, f'Prueba gratis activada: {dominio}',
                         f"Plan completo por 15 días. Vence el {vence}. WhatsApp: "
                         f"{compra.get('buyer_telefono') or 'sin dato'}."))
            titulo = f"Llamar a {compra.get('buyer_nombre') or compra.get('nombre_negocio')}: su prueba gratis vence el {vence}"
            cur.execute("SELECT 1 FROM crm_tareas WHERE contacto_id = %s AND titulo = %s", (cid, titulo))
            if not cur.fetchone():
                cur.execute("""INSERT INTO crm_tareas (contacto_id, titulo, descripcion, prioridad, fecha_limite)
                               VALUES (%s, %s, %s, 'alta', %s)""",
                            (cid, titulo,
                             f"Tienda: {dominio}\nWhatsApp: {compra.get('buyer_telefono') or 'sin dato'}\n"
                             f"Correo: {compra.get('buyer_email')}\n"
                             + (f"Link de pago: https://cybershopcol.com/renovar/{compra['token_renovacion']}"
                                if compra.get('token_renovacion') else ''),
                             date.today() + timedelta(days=DIA_SEGUIMIENTO - 1)))
            return cid
    except Exception:  # noqa: BLE001 — el CRM nunca debe tumbar la activación
        return None


# ── Pantalla «Pruebas gratis» ──────────────────────────────────
TOTAL_DIAS = 15


def _estado(f, hoy):
    """(clave, texto, días_restantes|None) en palabras para el operador."""
    estado = f['estado']
    if not f['es_trial'] and estado == 'ACTIVADA':
        return 'convertida', 'Ya es cliente (pagó)', None
    if estado == 'TRIAL_PENDIENTE':
        return 'pendiente', 'Esperando que confirme su correo', None
    if estado in ('PAGADO', 'ACTIVANDO'):
        return 'creando', 'Creando su tienda', None
    if estado == 'ERROR':
        return 'error', 'Falló la creación de la tienda', None
    if estado == 'ELIMINADA':
        return 'eliminada', 'Tienda eliminada', None
    if estado == 'CANCELADA':
        return 'eliminada', 'Tienda cancelada (apagada)', None
    if estado == 'ACTIVADA' and f['proximo_pago']:
        quedan = (f['proximo_pago'] - hoy).days
        if quedan < 0:
            return 'vencida', f'Vencida hace {-quedan} día{"s" if quedan != -1 else ""}', quedan
        if f.get('suspendida_por_pago'):
            return 'vencida', 'Suspendida por no pagar', quedan
        return ('por_vencer' if quedan <= 3 else 'activa',
                f'Activa — quedan {quedan} de {TOTAL_DIAS} días', quedan)
    return 'otro', estado.title(), None


def listar(filtro='todas', hoy=None):
    hoy = hoy or date.today()
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT to_regclass('plan_compras') IS NOT NULL AS hay")
        if not cur.fetchone()['hay']:
            return [], {}
        hay_crm = _hay_crm(cur)
        contacto_sql = ("(SELECT c.id FROM crm_contactos c WHERE LOWER(c.email) = LOWER(p.buyer_email) "
                        "ORDER BY c.activo DESC, c.id LIMIT 1)") if hay_crm else 'NULL'
        cur.execute(f"""
            SELECT p.id, p.estado, p.es_trial, p.nombre_negocio, p.buyer_nombre, p.buyer_email,
                   p.buyer_telefono, p.slug, p.dominio, p.proximo_pago, p.suspendida_por_pago,
                   p.token_renovacion, p.created_at, p.activated_at, p.error,
                   {contacto_sql} AS contacto_id
            FROM plan_compras p
            WHERE p.referencia_pedido LIKE 'TRIAL-%%' AND p.renovacion_de IS NULL
            ORDER BY p.created_at DESC
            LIMIT 300""")
        filas = [dict(f) for f in cur.fetchall()]
    conteo = {}
    salida = []
    for f in filas:
        clave, texto, quedan = _estado(f, hoy)
        f.update(estado_clave=clave, estado_texto=texto, dias_restantes=quedan,
                 progreso=(None if quedan is None else
                           max(0, min(100, round((TOTAL_DIAS - max(quedan, 0)) / TOTAL_DIAS * 100)))),
                 whatsapp_url=whatsapp_url(f.get('buyer_telefono')),
                 link_pago=(f"https://cybershopcol.com/renovar/{f['token_renovacion']}"
                            if f.get('token_renovacion') else None))
        conteo[clave] = conteo.get(clave, 0) + 1
        if filtro in ('todas', clave) or (filtro == 'activas' and clave in ('activa', 'por_vencer')):
            salida.append(f)
    return salida, conteo


def whatsapp_url(telefono):
    digitos = ''.join(ch for ch in str(telefono or '') if ch.isdigit())
    if len(digitos) == 10:
        digitos = '57' + digitos
    return f'https://wa.me/{digitos}' if len(digitos) >= 11 else None
