"""Cartera: qué está aprobado y todavía no lo han pagado.

Cuando se aprueba una cotización o se crea una cuenta de cobro, el sistema
registra el ingreso en contabilidad de una vez. Eso no cambia acá: la
contabilidad sigue igual y ningún reporte se mueve. Lo que este módulo agrega
es el **seguimiento del cobro**: si el cliente ya desembolsó o no.

Tres estados, guardados en la columna `estado_pago` (migración 0011):

    NULL         sin dato — documento viejo, o que nadie ha revisado todavía
    'pendiente'  aprobado pero el dinero no ha entrado
    'pagada'     el dinero entró (con `fecha_pago`)

"Sin dato" y "pendiente" son cosas distintas a propósito: no se inventa
información sobre documentos anteriores a esta función.

Todo aquí tolera que el cliente aún no haya actualizado su base: si la columna
no existe, se avisa con un mensaje entendible en vez de reventar.
"""

from datetime import date

from flask import current_app

from database import get_db_cursor
from helpers import formatear_moneda
from services.ia_datos.base import _columnas, _existe

# Días de plazo cuando el documento no trae fecha de vencimiento.
DIAS_PLAZO_DEFECTO = 30

ESTADOS = ('pendiente', 'pagada')
FILTROS = ('pendiente', 'pagada', 'sin_dato')

# Los dos tipos de documento que se cobran. `estado_sql` deja fuera lo que no
# es cartera (una cotización rechazada o sin aprobar no se le cobra a nadie).
DOCUMENTOS = {
    'cotizacion': {
        'tabla': 'cotizaciones',
        'etiqueta': 'Cotización',
        'estado_sql': "COALESCE(estado, 'pendiente') = 'aprobada'",
        'numero_sql': "'COT ' || LPAD(id::text, 10, '0')",
    },
    'cuenta_cobro': {
        'tabla': 'cuentas_cobro',
        'etiqueta': 'Cuenta de cobro',
        'estado_sql': 'TRUE',
        'numero_sql': "COALESCE(consecutivo, 'CC-' || id::text)",
    },
}

MSG_SIN_COLUMNA = ('Este negocio todavía no tiene el seguimiento de pagos. '
                   'Actualiza la app desde el panel y vuelve a intentarlo.')


# ── Soporte ────────────────────────────────────────────────────
def soporta_cartera(cur, tabla):
    """True si la tabla existe y ya tiene la columna de la migración 0011."""
    try:
        return _existe(cur, tabla) and 'estado_pago' in _columnas(cur, tabla)
    except Exception:
        return False


def cartera_disponible():
    """True si al menos uno de los dos documentos soporta cartera.
    Lo usan las plantillas para mostrar u ocultar los botones."""
    try:
        with get_db_cursor() as cur:
            return any(soporta_cartera(cur, d['tabla']) for d in DOCUMENTOS.values())
    except Exception:
        return False


def _doc(tipo):
    d = DOCUMENTOS.get(tipo)
    if not d:
        raise ValueError(f'tipo de documento desconocido: {tipo}')
    return d


# ── Escritura ──────────────────────────────────────────────────
def marcar_pago(tipo, doc_id, estado, fecha=None, nota=None):
    """Marca un documento como 'pendiente' o 'pagada'. Devuelve (ok, mensaje).

    `estado` vacío o 'sin_dato' vuelve el documento a "sin dato" (deshacer).
    """
    try:
        d = _doc(tipo)
    except ValueError:
        return False, 'Documento desconocido.'

    estado = (estado or '').strip().lower()
    if estado in ('', 'sin_dato', 'ninguno'):
        estado = None
    elif estado not in ESTADOS:
        return False, 'Estado de pago no válido.'

    fecha_pago = None
    if estado == 'pagada':
        fecha_pago = fecha or date.today()
    nota = (nota or '').strip()[:200] or None

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            if not soporta_cartera(cur, d['tabla']):
                return False, MSG_SIN_COLUMNA
            cur.execute(
                f"UPDATE {d['tabla']} SET estado_pago = %s, fecha_pago = %s, nota_pago = %s "
                f"WHERE id = %s RETURNING id",
                (estado, fecha_pago, nota, doc_id))
            if not cur.fetchone():
                return False, f"{d['etiqueta']} no encontrada."
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error(f'cartera: no se pudo marcar {tipo} {doc_id}: {exc}')
        return False, 'No se pudo guardar el estado de pago (revisa el log).'

    if estado == 'pagada':
        return True, f"{d['etiqueta']} marcada como PAGADA."
    if estado == 'pendiente':
        return True, f"{d['etiqueta']} marcada como PENDIENTE DE PAGO."
    return True, f"{d['etiqueta']}: se quitó el estado de pago."


def marcar_pendiente_si_falta(tipo, doc_id):
    """Deja el documento en 'pendiente' al nacer (aprobar / crear), solo si
    nadie le ha puesto estado todavía.

    Nunca interrumpe el flujo que la llama: si el cliente no ha actualizado la
    base, simplemente no hace nada.
    """
    try:
        d = _doc(tipo)
        with get_db_cursor() as cur:
            if not soporta_cartera(cur, d['tabla']):
                return False
            cur.execute(
                f"UPDATE {d['tabla']} SET estado_pago = 'pendiente' "
                f"WHERE id = %s AND estado_pago IS NULL", (doc_id,))
            return True
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f'cartera: no se pudo iniciar {tipo} {doc_id}: {exc}')
        return False


def estado_de(tipo, doc_id):
    """Estado de pago actual de un documento, o None si no aplica."""
    try:
        d = _doc(tipo)
        with get_db_cursor(dict_cursor=True) as cur:
            if not soporta_cartera(cur, d['tabla']):
                return None
            cur.execute(f"SELECT estado_pago FROM {d['tabla']} WHERE id = %s", (doc_id,))
            r = cur.fetchone()
            return r['estado_pago'] if r else None
    except Exception:
        return None


# ── Lectura ────────────────────────────────────────────────────
def sql_filtro(filtro):
    if filtro == 'pendiente':
        return "estado_pago = 'pendiente'"
    if filtro == 'pagada':
        return "estado_pago = 'pagada'"
    if filtro == 'sin_dato':
        return 'estado_pago IS NULL'
    return 'TRUE'


def _documentos(cur, tipo, filtro=None, limite=300):
    """Filas de cartera de un tipo de documento. Lista vacía si no aplica."""
    d = _doc(tipo)
    if not soporta_cartera(cur, d['tabla']):
        return []
    extra = 'consecutivo' if tipo == 'cuenta_cobro' else 'NULL'
    cur.execute(f"""
        SELECT id,
               {d['numero_sql']}                      AS numero,
               fecha,
               COALESCE(cliente_nombre, 'Sin nombre') AS cliente,
               COALESCE(total, 0)                     AS total,
               estado_pago,
               fecha_pago,
               nota_pago,
               COALESCE(fecha_vencimiento,
                        (fecha + INTERVAL '{DIAS_PLAZO_DEFECTO} days'))::date AS vence,
               {extra}                                AS consecutivo
        FROM {d['tabla']}
        WHERE {d['estado_sql']} AND {sql_filtro(filtro)}
        ORDER BY fecha DESC, id DESC
        LIMIT %s
    """, (limite,))
    hoy = date.today()
    filas = []
    for r in cur.fetchall():
        vence = r['vence']
        pendiente = r['estado_pago'] == 'pendiente'
        dias = (hoy - vence).days if (vence and pendiente) else 0
        filas.append({
            'tipo': tipo,
            'etiqueta': d['etiqueta'],
            'id': r['id'],
            'numero': r['numero'],
            'fecha': r['fecha'],
            'cliente': r['cliente'],
            'total': float(r['total'] or 0),
            'total_fmt': formatear_moneda(float(r['total'] or 0)),
            'estado_pago': r['estado_pago'],
            'fecha_pago': r['fecha_pago'],
            'nota_pago': r['nota_pago'],
            'vence': vence,
            'dias_mora': dias if dias > 0 else 0,
            'vencida': dias > 0,
        })
    return filas


def _clave_fecha(fila):
    """Fecha comparable entre tablas: una guarda DATE y la otra TIMESTAMP,
    y en Python comparar ambos tipos entre sí lanza TypeError."""
    f = fila.get('fecha')
    if f is None:
        return date.min
    return f.date() if hasattr(f, 'date') else f


def documentos_cartera(filtro=None, limite=300):
    """Cotizaciones aprobadas + cuentas de cobro, para la pantalla de cartera."""
    filas = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            for tipo in DOCUMENTOS:
                filas.extend(_documentos(cur, tipo, filtro, limite))
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error(f'cartera: no se pudo listar: {exc}')
    filas.sort(key=_clave_fecha, reverse=True)
    return filas


def resumen_cartera():
    """Totales de cartera: por cobrar, vencido, pagado y sin dato.

    Devuelve montos crudos (float) y `disponible=False` cuando el cliente aún
    no ha actualizado la base, para que la UI no muestre ceros engañosos.
    """
    base = {'disponible': False, 'pendiente_n': 0, 'pendiente_total': 0.0,
            'vencido_n': 0, 'vencido_total': 0.0, 'pagado_n': 0, 'pagado_total': 0.0,
            'sin_dato_n': 0, 'sin_dato_total': 0.0}
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            for tipo, d in DOCUMENTOS.items():
                if not soporta_cartera(cur, d['tabla']):
                    continue
                base['disponible'] = True
                cur.execute(f"""
                    SELECT COALESCE(estado_pago, 'sin_dato') AS est,
                           COUNT(*)                          AS n,
                           COALESCE(SUM(COALESCE(total, 0)), 0) AS t,
                           COUNT(*) FILTER (
                               WHERE estado_pago = 'pendiente'
                                 AND COALESCE(fecha_vencimiento,
                                     (fecha + INTERVAL '{DIAS_PLAZO_DEFECTO} days'))::date < CURRENT_DATE
                           ) AS n_venc,
                           COALESCE(SUM(COALESCE(total, 0)) FILTER (
                               WHERE estado_pago = 'pendiente'
                                 AND COALESCE(fecha_vencimiento,
                                     (fecha + INTERVAL '{DIAS_PLAZO_DEFECTO} days'))::date < CURRENT_DATE
                           ), 0) AS t_venc
                    FROM {d['tabla']}
                    WHERE {d['estado_sql']}
                    GROUP BY 1
                """)
                for r in cur.fetchall():
                    est = r['est']
                    if est in ('pendiente', 'pagada', 'sin_dato'):
                        clave = 'pagado' if est == 'pagada' else est
                        base[f'{clave}_n'] += int(r['n'])
                        base[f'{clave}_total'] += float(r['t'] or 0)
                    base['vencido_n'] += int(r['n_venc'] or 0)
                    base['vencido_total'] += float(r['t_venc'] or 0)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error(f'cartera: no se pudo resumir: {exc}')
    # Versión ya formateada para las plantillas (no hay filtro de moneda en Jinja).
    for clave in ('pendiente', 'vencido', 'pagado', 'sin_dato'):
        base[f'{clave}_fmt'] = formatear_moneda(base[f'{clave}_total'])
    return base
