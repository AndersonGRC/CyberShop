"""Piezas comunes de las herramientas de datos de la IA.

Cada herramienta es una consulta FIJA, parametrizada y de solo lectura sobre la
BD del tenant actual (get_db_cursor, sin tenant_id). La IA nunca escribe SQL:
solo elige el código de una herramienta y parámetros simples que se validan acá.
"""

from collections import namedtuple
from datetime import date, timedelta


# ── Períodos ───────────────────────────────────────────────────
# Los cuatro primeros son los históricos: su SQL no cambia para que las cifras
# de siempre sigan saliendo idénticas. Los demás se agregaron para preguntas
# como "¿y el mes pasado?" o "¿cuánto vendí ayer?".
_PERIODO_SQL = {
    'hoy':    "DATE({col}) = CURRENT_DATE",
    'semana': "{col} >= date_trunc('week', CURRENT_DATE)",
    'mes':    "{col} >= date_trunc('month', CURRENT_DATE)",
    'todo':   "TRUE",
    'ayer':   "DATE({col}) = CURRENT_DATE - 1",
    'semana_anterior': ("{col} >= date_trunc('week', CURRENT_DATE) - INTERVAL '7 days' "
                        "AND {col} < date_trunc('week', CURRENT_DATE)"),
    'mes_anterior': ("{col} >= date_trunc('month', CURRENT_DATE) - INTERVAL '1 month' "
                     "AND {col} < date_trunc('month', CURRENT_DATE)"),
    'anio':   "{col} >= date_trunc('year', CURRENT_DATE)",
}
_PERIODO_LABEL = {
    'hoy': 'hoy', 'semana': 'esta semana', 'mes': 'este mes', 'todo': 'en total',
    'ayer': 'ayer', 'semana_anterior': 'la semana pasada', 'mes_anterior': 'el mes pasado',
    'anio': 'este año',
}
PERIODOS = tuple(_PERIODO_SQL)

# Rango explícito de fechas (ambas inclusivas), p. ej. "en agosto".
Rango = namedtuple('Rango', 'desde hasta')
_RANGO_MAX_DIAS = 3 * 366


def _periodo(p):
    if isinstance(p, Rango):
        return p
    return p if p in _PERIODO_SQL else 'mes'


def _label_periodo(p):
    p = _periodo(p)
    if isinstance(p, Rango):
        if p.desde == p.hasta:
            return f'el {p.desde:%d/%m/%Y}'
        return f'del {p.desde:%d/%m/%Y} al {p.hasta:%d/%m/%Y}'
    return _PERIODO_LABEL[p]


def _sql_periodo(p, col):
    """Filtro SQL del período sobre `col`. Las fechas de un Rango son objetos
    date ya validados, así que su isoformat() solo tiene dígitos y guiones."""
    p = _periodo(p)
    if isinstance(p, Rango):
        return (f"{col} >= DATE '{p.desde.isoformat()}' "
                f"AND {col} < DATE '{p.hasta.isoformat()}' + 1")
    return _PERIODO_SQL[p].format(col=col)


def rango_efectivo(hoy, periodo):
    """(desde, hasta) en fechas reales del período, ambas inclusive. 'todo' →
    (None, hasta): sin inicio conocido."""
    p = _periodo(periodo)
    if isinstance(p, Rango):
        return p.desde, p.hasta
    lunes = hoy - timedelta(days=hoy.weekday())
    mes1 = hoy.replace(day=1)
    mes_ant_fin = mes1 - timedelta(days=1)
    return {
        'hoy': (hoy, hoy),
        'ayer': (hoy - timedelta(days=1), hoy - timedelta(days=1)),
        'semana': (lunes, hoy),
        'semana_anterior': (lunes - timedelta(days=7), lunes - timedelta(days=1)),
        'mes': (mes1, hoy),
        'mes_anterior': (mes_ant_fin.replace(day=1), mes_ant_fin),
        'anio': (hoy.replace(month=1, day=1), hoy),
        'todo': (None, hoy),
    }[p]


def rango_anterior(desde, hasta, periodo=None):
    """Período comparable inmediatamente anterior, del mismo tamaño. Para 'mes'
    y 'anio' (que van del día 1 a hoy) se toma el mismo tramo del período
    anterior, no los 30 días previos: comparar 15 días contra 30 engañaría."""
    if desde is None:
        return None, None
    p = _periodo(periodo) if periodo is not None else None
    if p == 'mes':
        ini = (desde - timedelta(days=1)).replace(day=1)
        return ini, min(ini + (hasta - desde), desde - timedelta(days=1))
    if p == 'anio':
        try:
            return desde.replace(year=desde.year - 1), hasta.replace(year=hasta.year - 1)
        except ValueError:                      # 29 de febrero
            return desde.replace(year=desde.year - 1, day=28), hasta.replace(year=hasta.year - 1, day=28)
    dias = (hasta - desde).days + 1
    return desde - timedelta(days=dias), desde - timedelta(days=1)


def etiqueta_rango(desde, hasta):
    if desde is None:
        return 'en total'
    if desde == hasta:
        return f'el {desde:%d/%m/%Y}'
    return f'del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}'


def cambio_pct(actual, anterior):
    """'+12%' / '-5%' / None si no hay base de comparación."""
    try:
        actual, anterior = float(actual), float(anterior)
    except (TypeError, ValueError):
        return None
    if anterior == 0:
        return None if actual == 0 else 'sin base de comparación (antes no hubo)'
    return f'{(actual - anterior) / abs(anterior) * 100:+.0f}%'


def rango_desde_params(params, hoy=None):
    """Rango validado a partir de `desde`/`hasta` (AAAA-MM-DD) o None si no
    vienen o no son fechas. Nunca pasa de hoy ni abarca más de 3 años."""
    params = params or {}
    txt_desde, txt_hasta = params.get('desde'), params.get('hasta')
    if not txt_desde and not txt_hasta:
        return None
    hoy = hoy or date.today()
    try:
        desde = date.fromisoformat(str(txt_desde)[:10]) if txt_desde else None
        hasta = date.fromisoformat(str(txt_hasta)[:10]) if txt_hasta else None
    except ValueError:
        return None
    hasta = min(hasta or hoy, hoy)
    desde = desde or hasta
    if desde > hasta:
        desde, hasta = hasta, desde
    if (hasta - desde).days > _RANGO_MAX_DIAS:
        desde = hasta - timedelta(days=_RANGO_MAX_DIAS)
    return Rango(desde, hasta)


# ── Utilidades de consulta ─────────────────────────────────────
# Pedidos web que cuentan como venta REAL (pago confirmado)
_PEDIDO_PAGADO = "estado_pago IN ('APROBADO','PAGADO','aprobado','pagado')"


def _existe(cur, tabla):
    """True si la tabla existe (algunos tenants no tienen todas las tablas)."""
    cur.execute("SELECT to_regclass(%s)", (f'public.{tabla}',))
    return cur.fetchone()[0] is not None


def _columnas(cur, tabla):
    cur.execute("SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s", (tabla,))
    return {r[0] for r in cur.fetchall()}


def _suma(cur, sql, cero=(0, 0)):
    """Ejecuta una suma y deja que un error de BD llegue al llamador.

    `cero` se conserva en la firma por compatibilidad; solo una fuente POS
    opcional *confirmada como ausente* puede aportar ceros. Ocultar un error SQL
    aquí convertiría una consulta fallida en una cifra de ventas falsa.
    """
    cur.execute(sql)
    r = cur.fetchone()
    return r['n'], float(r['t'])


# ── Registro de herramientas ───────────────────────────────────
# Vive en services/ia/registro.py: es el registro ÚNICO del asistente, el mismo
# que usan el enrutador por palabras clave y el mapa de docs/IA_MAPA.md. Se
# reexporta aquí porque los módulos de dominio (y la fachada ai_tools) lo
# importan desde este archivo desde siempre.
from services.ia.registro import (  # noqa: E402,F401
    REGISTRO, Capacidad, Herramienta, registrar,
)
