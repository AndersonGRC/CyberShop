"""Piezas comunes de las herramientas de datos de la IA.

Cada herramienta es una consulta FIJA, parametrizada y de solo lectura sobre la
BD del tenant actual (get_db_cursor, sin tenant_id). La IA nunca escribe SQL:
solo elige el código de una herramienta y parámetros simples que se validan acá.
"""

from collections import namedtuple
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Optional, Tuple


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
    """Ejecuta una suma; devuelve (n, total) o ceros si algo falla."""
    try:
        cur.execute(sql)
        r = cur.fetchone()
        return r['n'], float(r['t'])
    except Exception:
        return cero


# ── Registro de herramientas ───────────────────────────────────
@dataclass(frozen=True)
class Herramienta:
    """Una consulta que la IA puede elegir.

    modulos:  módulos del plan que deben estar activos (vacío = siempre).
    permiso:  módulo de la matriz de permisos que el rol debe poder 'ver'
              (None = basta con poder usar el asistente).
    sensible: None, o 'nomina' para datos que solo ven dueño y contador.
    etiqueta: cómo se nombra al avisar "Consultando {etiqueta}…".
    """
    code: str
    fn: Callable
    descripcion: str
    params: Tuple[str, ...] = ()
    etiqueta: str = 'los datos de tu negocio'
    dominio: str = 'general'
    modulos: Tuple[str, ...] = ()
    permiso: Optional[str] = None
    sensible: Optional[str] = None
    extra: dict = field(default_factory=dict, compare=False)


REGISTRO = {}


def registrar(code, fn, descripcion, params=(), **kw):
    REGISTRO[code] = Herramienta(code, fn, descripcion, tuple(params), **kw)
    return REGISTRO[code]
