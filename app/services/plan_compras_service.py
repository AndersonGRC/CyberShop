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
           'TRIAL_PENDIENTE')

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

def crear_trial(nombre_negocio, buyer_nombre, buyer_email, slug, telefono=''):
    """Registro de prueba gratis: fila TRIAL_PENDIENTE con token de
    verificación de email. Devuelve (compra_id, token) o (None, error)."""
    _ensure_table()
    buyer_email = (buyer_email or '').strip().lower()
    with get_db_cursor(dict_cursor=True) as cur:
        # Antiabuso: un solo trial por email (pendiente o ya usado)
        cur.execute(
            "SELECT 1 FROM plan_compras WHERE LOWER(buyer_email) = %s AND es_trial = TRUE",
            (buyer_email,),
        )
        if cur.fetchone():
            return None, 'Ese correo ya usó una prueba gratis. Escríbenos y te ayudamos.'
        cur.execute(
            "SELECT 1 FROM plan_compras WHERE slug = %s AND estado IN ('TRIAL_PENDIENTE','ACTIVANDO','ACTIVADA')",
            (slug,),
        )
        if cur.fetchone():
            return None, 'Ese subdominio ya está en uso. Elige otro.'
        token = secrets.token_urlsafe(24)
        referencia = f"TRIAL-{secrets.token_hex(8).upper()}"
        cur.execute(
            """
            INSERT INTO plan_compras
                (referencia_pedido, plan_key, buyer_nombre, buyer_email,
                 buyer_telefono, nombre_negocio, slug, token, estado,
                 periodo, es_trial)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'TRIAL_PENDIENTE', 'mes', TRUE)
            RETURNING id
            """,
            (referencia, TRIAL_PLAN_KEY, buyer_nombre, buyer_email,
             telefono, nombre_negocio, slug, token),
        )
        return cur.fetchone()['id'], token


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

def extender_periodo(compra_id):
    """Renovación pagada: corre proximo_pago un período y limpia recordatorios.
    Devuelve la fila actualizada."""
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT periodo, proximo_pago FROM plan_compras WHERE id = %s", (compra_id,))
        row = cur.fetchone()
        if not row:
            return None
        delta = timedelta(days=365) if row['periodo'] == 'año' else timedelta(days=30)
        base = row['proximo_pago'] or date.today()
        # Si pagó tarde, el nuevo período corre desde HOY (no acumula deuda de días)
        if base < date.today():
            base = date.today()
        cur.execute(
            """
            UPDATE plan_compras
            SET proximo_pago = %s, ultimo_recordatorio = NULL,
                suspendida_por_pago = FALSE
            WHERE id = %s
            RETURNING *
            """,
            (base + delta, compra_id),
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
