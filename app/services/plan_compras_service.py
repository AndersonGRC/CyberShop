"""Compras de planes del Software CyberShop: venta automática y renovaciones.

Registra cada compra de plan (tabla `plan_compras`), gobierna su ciclo de vida
y las fechas de cobro recurrente:

    PENDIENTE_PAGO ──pago aprobado──> PAGADO (token de activación emitido)
        └─ plan anual: queda CONTACTO (manejo manual, solo correos)
    PAGADO ──cliente activa──> ACTIVANDO ──maestro crea tenant──> ACTIVADA
                                   └────────────fallo───────────> ERROR (reintentable)

Las renovaciones son filas nuevas con `renovacion_de` apuntando a la compra
original; al aprobarse el pago extienden `proximo_pago` del padre.
"""

import calendar
import secrets
from datetime import date, datetime, timedelta

from database import get_db_cursor


# Solo los planes MENSUALES crean tienda automática (decisión de negocio).
# Mapeo plan_key (software_planes) -> nivel de módulos del maestro.
PLANES_AUTOMATICOS = {
    'software-cybershop': 'estandar',
    'ultra': 'ultra',
}

ESTADOS = ('PENDIENTE_PAGO', 'PAGADO', 'CONTACTO', 'ACTIVANDO', 'ACTIVADA', 'ERROR',
           'TRIAL_PENDIENTE',
           # El maestro cierra la compra al cancelar (CANCELADA, reversible) o
           # eliminar (ELIMINADA) la tienda: el cron deja de cobrarla.
           'CANCELADA', 'ELIMINADA')

TRIAL_DIAS = 15          # duración de la prueba gratis
TRIAL_PLAN_KEY = 'ultra'  # decisión de negocio: toda prueba usa el plan completo


def _ensure_table():
    with get_db_cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS plan_compras (
                id                  SERIAL PRIMARY KEY,
                pedido_id           INTEGER,
                referencia_pedido   VARCHAR(80) UNIQUE NOT NULL,
                plan_key            VARCHAR(60) NOT NULL,
                buyer_nombre        VARCHAR(150),
                buyer_email         VARCHAR(150) NOT NULL,
                token               VARCHAR(80) UNIQUE,
                token_renovacion    VARCHAR(80) UNIQUE,
                estado              VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE_PAGO',
                tenant_id           INTEGER,
                slug                VARCHAR(60),
                dominio             VARCHAR(200),
                error               TEXT,
                periodo             VARCHAR(10) NOT NULL DEFAULT 'mes',
                proximo_pago        DATE,
                ultimo_recordatorio VARCHAR(20),
                suspendida_por_pago BOOLEAN NOT NULL DEFAULT FALSE,
                renovacion_de       INTEGER REFERENCES plan_compras(id),
                created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                activated_at        TIMESTAMP
            )
            """
        )
        # Prueba gratis 15 días (aditivo/idempotente)
        cur.execute("ALTER TABLE plan_compras ADD COLUMN IF NOT EXISTS es_trial BOOLEAN NOT NULL DEFAULT FALSE")
        cur.execute("ALTER TABLE plan_compras ADD COLUMN IF NOT EXISTS nombre_negocio VARCHAR(150)")
        cur.execute("ALTER TABLE plan_compras ADD COLUMN IF NOT EXISTS buyer_telefono VARCHAR(40)")
        # Asistente de la prueba gratis (aditivo): color de marca y tipo de negocio
        cur.execute("ALTER TABLE plan_compras ADD COLUMN IF NOT EXISTS color_marca VARCHAR(7)")
        cur.execute("ALTER TABLE plan_compras ADD COLUMN IF NOT EXISTS tipo_negocio VARCHAR(30)")
        cur.execute("ALTER TABLE plan_compras ADD COLUMN IF NOT EXISTS lema VARCHAR(120)")
        # Cuándo se envió el último enlace de confirmación (vence a las 72 h).
        cur.execute("ALTER TABLE plan_compras ADD COLUMN IF NOT EXISTS verificacion_enviada_at TIMESTAMP")


def normalizar_whatsapp(valor):
    """WhatsApp colombiano a 10 dígitos: acepta espacios, guiones y +57.
    Devuelve (numero, None) o (None, mensaje)."""
    digitos = ''.join(ch for ch in str(valor or '') if ch.isdigit())
    if len(digitos) == 12 and digitos.startswith('57'):
        digitos = digitos[2:]
    if len(digitos) != 10 or not (digitos.startswith('3') or digitos.startswith('60')):
        return None, ('Escribe tu WhatsApp de 10 dígitos (ej. 300 123 4567). '
                      'Es el número por el que te ayudaremos durante la prueba.')
    return digitos, None


ESTADOS_QUE_RESERVAN = ('TRIAL_PENDIENTE', 'PAGADO', 'ACTIVANDO', 'ACTIVADA')
VERIFICACION_HORAS = 72      # el enlace de confirmación vence; mientras, aparta el subdominio
# Una prueba sin confirmar solo aparta su subdominio mientras su enlace esté
# vigente: un correo falso o de spam no bloquea direcciones para siempre.
_RESERVA_VIGENTE = (f"NOT (estado = 'TRIAL_PENDIENTE' AND COALESCE(verificacion_enviada_at, created_at)"
                    f" < NOW() - INTERVAL '{VERIFICACION_HORAS} hours')")


def confirmacion_vigente(compra):
    """¿Este enlace de prueba se puede usar todavía?"""
    if not compra or compra.get('estado') != 'TRIAL_PENDIENTE':
        return True          # ya confirmada: el enlace lleva a la página de activación
    enviado = compra.get('verificacion_enviada_at') or compra.get('created_at')
    return bool(enviado) and enviado >= datetime.now() - timedelta(hours=VERIFICACION_HORAS)


def slug_reservado(slug, excluir_id=None):
    """¿Otra compra o prueba ya apartó este subdominio? `excluir_id`: la prueba
    pendiente de la misma persona (su propia reserva no le cuenta como ocupada)."""
    _ensure_table()
    with get_db_cursor() as cur:
        cur.execute("SELECT 1 FROM plan_compras WHERE slug = %s AND estado = ANY(%s) "
                    f"AND id <> COALESCE(%s, 0) AND {_RESERVA_VIGENTE} LIMIT 1",
                    (slug, list(ESTADOS_QUE_RESERVAN), excluir_id))
        return cur.fetchone() is not None


def crear_compra(pedido_id, referencia, plan_key, buyer_nombre, buyer_email,
                 periodo='mes', renovacion_de=None):
    """Registra la compra de un plan al crear el pedido (antes de ir a PayU)."""
    _ensure_table()
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            INSERT INTO plan_compras
                (pedido_id, referencia_pedido, plan_key, buyer_nombre,
                 buyer_email, periodo, renovacion_de)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (referencia_pedido) DO NOTHING
            RETURNING id
            """,
            (pedido_id, referencia, plan_key, buyer_nombre, buyer_email,
             periodo, renovacion_de),
        )
        row = cur.fetchone()
        return row['id'] if row else None


def get_por_referencia(referencia):
    _ensure_table()
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM plan_compras WHERE referencia_pedido = %s", (referencia,))
        return cur.fetchone()


def get_por_token(token):
    if not token:
        return None
    _ensure_table()
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM plan_compras WHERE token = %s", (token,))
        return cur.fetchone()


def get_por_token_renovacion(token):
    if not token:
        return None
    _ensure_table()
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM plan_compras WHERE token_renovacion = %s", (token,))
        return cur.fetchone()


def get_por_id(compra_id):
    _ensure_table()
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM plan_compras WHERE id = %s", (compra_id,))
        return cur.fetchone()


# ── Transiciones de estado (idempotentes) ──────────────────────

def marcar_pagada_con_token(compra_id):
    """PENDIENTE_PAGO -> PAGADO emitiendo token de activación (una sola vez).
    Devuelve el token, o None si la compra ya fue procesada (idempotencia)."""
    token = secrets.token_urlsafe(24)
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            UPDATE plan_compras SET estado = 'PAGADO', token = %s
            WHERE id = %s AND estado = 'PENDIENTE_PAGO'
            RETURNING token
            """,
            (token, compra_id),
        )
        row = cur.fetchone()
        return row['token'] if row else None


def marcar_contacto(compra_id):
    """PENDIENTE_PAGO -> CONTACTO (planes anuales: manejo manual)."""
    with get_db_cursor() as cur:
        cur.execute(
            "UPDATE plan_compras SET estado = 'CONTACTO' "
            "WHERE id = %s AND estado = 'PENDIENTE_PAGO'",
            (compra_id,),
        )
        return cur.rowcount > 0


def marcar_activando(compra_id, slug):
    """PAGADO/ERROR -> ACTIVANDO (reserva el intento; evita doble submit)."""
    with get_db_cursor() as cur:
        cur.execute(
            """
            UPDATE plan_compras SET estado = 'ACTIVANDO', slug = %s, error = NULL
            WHERE id = %s AND estado IN ('PAGADO', 'ERROR')
            """,
            (slug, compra_id),
        )
        return cur.rowcount > 0


def marcar_activada(compra_id, tenant_id, slug, dominio, periodo='mes', dias=None):
    """ACTIVANDO -> ACTIVADA: tienda creada. Fija proximo_pago y emite el
    token de renovación permanente (para los recordatorios de cobro).
    `dias` fuerza el vencimiento (p.ej. 15 para la prueba gratis)."""
    if dias is not None:
        delta = timedelta(days=int(dias))
    else:
        delta = timedelta(days=365) if periodo == 'año' else timedelta(days=30)
    with get_db_cursor() as cur:
        cur.execute(
            """
            UPDATE plan_compras
            SET estado = 'ACTIVADA', tenant_id = %s, slug = %s, dominio = %s,
                activated_at = NOW(), proximo_pago = %s,
                token_renovacion = COALESCE(token_renovacion, %s)
            WHERE id = %s
            """,
            (tenant_id, slug, dominio, date.today() + delta,
             secrets.token_urlsafe(24), compra_id),
        )


# ── Prueba gratis (trial 15 días, plan Ultra, sin pago) ────────

def crear_trial(nombre_negocio, buyer_nombre, buyer_email, slug, telefono='',
                color_marca=None, tipo_negocio=None, lema=None):
    """Registro de prueba gratis: fila TRIAL_PENDIENTE con token de
    verificación de email. Devuelve (compra_id, token) o (None, error).
    En la misma transacción deja al interesado en el CRM del operador."""
    _ensure_table()
    buyer_email = (buyer_email or '').strip().lower()
    with get_db_cursor(dict_cursor=True) as cur:
        # Antiabuso: un solo trial por email. Si el anterior NUNCA confirmó el
        # correo (no llegó, se perdió), se actualizan sus datos y se reenvía el
        # mismo enlace en vez de dejar a la persona bloqueada.
        cur.execute(
            "SELECT id, estado, token FROM plan_compras "
            "WHERE LOWER(buyer_email) = %s AND referencia_pedido LIKE 'TRIAL-%%' "
            "ORDER BY id DESC LIMIT 1",
            (buyer_email,),
        )
        previa = cur.fetchone()
        if previa and previa['estado'] != 'TRIAL_PENDIENTE':
            return None, 'Ese correo ya usó una prueba gratis. Escríbenos y te ayudamos.'
        cur.execute(
            "SELECT 1 FROM plan_compras WHERE slug = %s AND estado = ANY(%s) "
            f"AND id <> COALESCE(%s, 0) AND {_RESERVA_VIGENTE}",
            (slug, list(ESTADOS_QUE_RESERVAN), previa['id'] if previa else None),
        )
        if cur.fetchone():
            return None, 'Ese subdominio ya está en uso. Elige otro.'
        if previa:
            cur.execute(
                """UPDATE plan_compras
                   SET buyer_nombre = %s, buyer_telefono = %s, nombre_negocio = %s, slug = %s,
                       color_marca = %s, tipo_negocio = %s, lema = %s,
                       verificacion_enviada_at = NOW()
                   WHERE id = %s AND estado = 'TRIAL_PENDIENTE'""",
                (buyer_nombre, telefono, nombre_negocio, slug, color_marca, tipo_negocio,
                 lema or None, previa['id']),
            )
            return previa['id'], previa['token']
        token = secrets.token_urlsafe(24)
        referencia = f"TRIAL-{secrets.token_hex(8).upper()}"
        cur.execute(
            """
            INSERT INTO plan_compras
                (referencia_pedido, plan_key, buyer_nombre, buyer_email,
                 buyer_telefono, nombre_negocio, slug, token, estado,
                 periodo, es_trial, color_marca, tipo_negocio, lema, verificacion_enviada_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'TRIAL_PENDIENTE', 'mes', TRUE, %s, %s, %s, NOW())
            RETURNING id
            """,
            (referencia, TRIAL_PLAN_KEY, buyer_nombre, buyer_email,
             telefono, nombre_negocio, slug, token, color_marca, tipo_negocio, lema or None),
        )
        compra_id = cur.fetchone()['id']
        # El interesado queda en el CRM desde ya (aunque no confirme el correo,
        # se le puede escribir por WhatsApp). Si el CRM falla, el registro sigue.
        try:
            cur.execute('SAVEPOINT crm_prueba')
            from services.crm_pruebas_service import registrar_interesado
            registrar_interesado(cur, nombre=buyer_nombre, email=buyer_email, telefono=telefono,
                                 negocio=nombre_negocio, slug=slug, tipo_negocio=tipo_negocio)
            cur.execute('RELEASE SAVEPOINT crm_prueba')
        except Exception:  # noqa: BLE001
            cur.execute('ROLLBACK TO SAVEPOINT crm_prueba')
        return compra_id, token


def reenviar_trial(compra_id):
    """Pide otro correo de confirmación (mismo enlace, vigencia renovada).
    Devuelve la fila o None si ya no está pendiente."""
    _ensure_table()
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""UPDATE plan_compras SET verificacion_enviada_at = NOW()
                       WHERE id = %s AND estado = 'TRIAL_PENDIENTE' RETURNING *""", (compra_id,))
        return cur.fetchone()


def cambiar_correo_trial(compra_id, nuevo_email):
    """La persona escribió mal su correo: lo cambia y emite un enlace NUEVO
    (el enviado al correo equivocado deja de servir). También corrige el
    contacto del CRM que creó este registro. Devuelve (fila, None) o (None, error)."""
    _ensure_table()
    nuevo_email = (nuevo_email or '').strip().lower()
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM plan_compras WHERE id = %s FOR UPDATE", (compra_id,))
        compra = cur.fetchone()
        if not compra or compra['estado'] != 'TRIAL_PENDIENTE':
            return None, 'Este registro ya fue confirmado o no existe. Si necesitas ayuda, escríbenos.'
        if compra['buyer_email'] == nuevo_email:
            return None, 'Ese es el mismo correo. Si no te llega, revisa spam o pide reenviarlo.'
        cur.execute("SELECT 1 FROM plan_compras WHERE LOWER(buyer_email) = %s "
                    "AND referencia_pedido LIKE 'TRIAL-%%' AND id <> %s", (nuevo_email, compra_id))
        if cur.fetchone():
            return None, 'Ese correo ya usó una prueba gratis. Escríbenos y te ayudamos.'
        cur.execute("""UPDATE plan_compras SET buyer_email = %s, token = %s, verificacion_enviada_at = NOW()
                       WHERE id = %s RETURNING *""", (nuevo_email, secrets.token_urlsafe(24), compra_id))
        fila = cur.fetchone()
        try:
            cur.execute('SAVEPOINT crm_correo')
            cur.execute("SELECT to_regclass('crm_contactos') IS NOT NULL AS hay")
            if cur.fetchone()['hay']:
                cur.execute("""UPDATE crm_contactos SET email = %s, updated_at = CURRENT_TIMESTAMP
                               WHERE LOWER(email) = %s AND origen = 'prueba_gratis'
                                 AND NOT EXISTS (SELECT 1 FROM crm_contactos c2 WHERE LOWER(c2.email) = %s)""",
                            (nuevo_email, compra['buyer_email'].lower(), nuevo_email))
            cur.execute('RELEASE SAVEPOINT crm_correo')
        except Exception:  # noqa: BLE001
            cur.execute('ROLLBACK TO SAVEPOINT crm_correo')
        return fila, None


def marcar_trial_verificado(compra_id):
    """TRIAL_PENDIENTE -> PAGADO (email verificado; entra al mismo camino de
    activación que una compra pagada). Idempotente."""
    with get_db_cursor() as cur:
        cur.execute(
            "UPDATE plan_compras SET estado = 'PAGADO' "
            "WHERE id = %s AND estado = 'TRIAL_PENDIENTE'",
            (compra_id,),
        )
        return cur.rowcount > 0


def marcar_trial_convertido(compra_id):
    """El trial pagó: deja de ser prueba (los recordatorios pasan al ciclo
    normal previo/día0/vencido)."""
    with get_db_cursor() as cur:
        cur.execute(
            "UPDATE plan_compras SET es_trial = FALSE WHERE id = %s",
            (compra_id,),
        )


def marcar_error(compra_id, detalle):
    """ACTIVANDO -> ERROR (reintentable reabriendo el link de activación)."""
    with get_db_cursor() as cur:
        cur.execute(
            "UPDATE plan_compras SET estado = 'ERROR', error = %s WHERE id = %s",
            (str(detalle)[:500], compra_id),
        )


# ── Cobro recurrente ───────────────────────────────────────────

def _sumar_meses(d, meses):
    """La misma fecha `meses` meses después (el 31 en un mes corto es su último día)."""
    m = d.month - 1 + meses
    anio, mes = d.year + m // 12, m % 12 + 1
    return date(anio, mes, min(d.day, calendar.monthrange(anio, mes)[1]))


def siguiente_vencimiento(proximo_pago, periodo='mes', hoy=None):
    """Próximo cobro tras pagar UN período, sobre la fecha de corte: el día de
    pago no cambia aunque pague tarde (vencía el 18, paga el 7 → vuelve a vencer
    el 18). Si aun así queda atrás de hoy (más de un período de atraso), avanza
    períodos completos en el mismo día hasta quedar al día: el pago en línea es
    de un período y no se acumula deuda. Antes contaba 30 días desde HOY y el
    día de cobro se corría."""
    hoy = hoy or date.today()
    meses = 12 if periodo == 'año' else 1
    if not proximo_pago:
        return _sumar_meses(hoy, meses)
    veces = 1
    nueva = _sumar_meses(proximo_pago, meses)
    while nueva < hoy:
        veces += 1
        nueva = _sumar_meses(proximo_pago, meses * veces)   # desde el corte: sin arrastrar el día
    return nueva


def extender_periodo(compra_id):
    """Renovación pagada: corre proximo_pago un período (ver
    `siguiente_vencimiento`) y limpia recordatorios. Devuelve la fila actualizada."""
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT periodo, proximo_pago FROM plan_compras WHERE id = %s", (compra_id,))
        row = cur.fetchone()
        if not row:
            return None
        nueva = siguiente_vencimiento(row['proximo_pago'], row['periodo'])
        cur.execute(
            """
            UPDATE plan_compras
            SET proximo_pago = %s, ultimo_recordatorio = NULL,
                suspendida_por_pago = FALSE
            WHERE id = %s
            RETURNING *
            """,
            (nueva, compra_id),
        )
        return cur.fetchone()


def marcar_recordatorio(compra_id, etapa):
    with get_db_cursor() as cur:
        cur.execute(
            "UPDATE plan_compras SET ultimo_recordatorio = %s WHERE id = %s",
            (etapa, compra_id),
        )


def marcar_suspendida_por_pago(compra_id):
    with get_db_cursor() as cur:
        cur.execute(
            "UPDATE plan_compras SET suspendida_por_pago = TRUE WHERE id = %s",
            (compra_id,),
        )


def compras_para_recordatorio():
    """Compras ACTIVADAS con fecha de cobro: el cron decide la etapa según
    proximo_pago vs hoy y ultimo_recordatorio (sin duplicados)."""
    _ensure_table()
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT * FROM plan_compras
            WHERE estado = 'ACTIVADA' AND proximo_pago IS NOT NULL
              AND renovacion_de IS NULL
            ORDER BY proximo_pago
            """
        )
        return cur.fetchall()
