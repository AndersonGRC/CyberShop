"""Herramientas de datos del Asistente IA, agrupadas por dominio.

SEGURIDAD / AISLAMIENTO:
- Cada función consulta SOLO la BD del tenant actual vía get_db_cursor()
  (resuelto por el request). No reciben tenant_id.
- Son consultas FIJAS y parametrizadas. La IA NUNCA escribe SQL: solo elige el
  NOMBRE de una herramienta de este catálogo y parámetros simples que se
  validan/clampan aquí.
- Devuelven datos estructurados (dict). El orquestador se los pasa a la IA para
  redactar la respuesta, así las cifras son SIEMPRE reales (la IA no las inventa).
- Cada herramienta declara qué módulo y qué permiso exige (ver acceso.py).

Para agregar una herramienta: escribir la función en el módulo de su dominio y
registrarla abajo, en el orden en que debe aparecer en el catálogo.
"""

from services.ia_datos.acceso import (
    CANAL_ESCRITORIO, CANAL_SISTEMA, CANAL_WEB, Contexto, contexto_actual, puede_usar,
)
from services.ia_datos.acceso import permitidas as _permitidas
from services.ia_datos.base import (
    PERIODOS, REGISTRO, Herramienta, Rango, _periodo, rango_desde_params, registrar,
)
from services.ia_datos import inventario as _inv
from services.ia_datos import ventas as _ven


# ── Catálogo (orden = orden en que la IA ve las herramientas) ──
registrar('ventas_periodo', _ven.ventas_periodo,
          "Ventas e ingresos de un período (hoy, ayer, semana, mes, año o fechas).",
          ['periodo'], etiqueta='tus ventas', dominio='ventas')
registrar('top_productos', _ven.top_productos,
          "Productos más vendidos en un período.",
          ['periodo', 'limite'], etiqueta='tus productos más vendidos', dominio='ventas')
registrar('top_clientes', _ven.top_clientes,
          "Clientes que más han comprado.",
          ['limite'], etiqueta='tus mejores clientes', dominio='clientes')
registrar('productos_bajo_stock', _inv.productos_bajo_stock,
          "Productos con stock bajo o agotados (parámetro: umbral).",
          ['umbral'], etiqueta='el stock de tus productos', dominio='inventario')
registrar('sugerencia_reorden', _inv.sugerencia_reorden,
          "Qué comprar/reponer pronto: productos que se agotan según su ritmo de venta, con cantidad sugerida.",
          [], etiqueta='el ritmo de venta y tu inventario', dominio='inventario')
registrar('catalogo_pendiente', _inv.catalogo_pendiente,
          "Qué falta por completar en el catálogo (sin descripción, imagen o categoría).",
          [], etiqueta='el estado de tu catálogo', dominio='inventario')
registrar('resumen_inventario', _inv.resumen_inventario,
          "Tamaño y valor del inventario.",
          [], etiqueta='tu inventario', dominio='inventario')
registrar('conteo_general', _ven.conteo_general,
          "Números generales: productos, categorías, clientes, pedidos.",
          [], etiqueta='los números generales de tu negocio', dominio='general')
registrar('pedidos_por_despachar', _ven.pedidos_por_despachar,
          "Pedidos web pagados pendientes de enviar.",
          [], etiqueta='tus pedidos por despachar', dominio='pedidos')
registrar('tendencia_ventas', _ven.tendencia_ventas,
          "Tendencia de las ventas en el tiempo: si suben, bajan o están estables, qué tan confiable es (R²), proyección de 7 días y mejor día de la semana.",
          [], etiqueta='la tendencia de tus ventas', dominio='ventas')
registrar('segmentos_clientes', _ven.segmentos_clientes,
          "Agrupa a los clientes en segmentos (fieles, nuevos, en riesgo, ocasionales) con análisis estadístico, para saber a quién cuidar o recuperar.",
          [], etiqueta='el comportamiento de tus clientes', dominio='clientes')

# Compatibilidad: code -> (función, descripción, params permitidos)
TOOLS = {h.code: (h.fn, h.descripcion, list(h.params)) for h in REGISTRO.values()}

_ALIAS_PERIODO = {
    'año': 'anio', 'ano': 'anio', 'este_anio': 'anio', 'semana_pasada': 'semana_anterior',
    'mes_pasado': 'mes_anterior', 'historico': 'todo', 'histórico': 'todo', 'siempre': 'todo',
}
# Filtros de texto que algunas herramientas aceptan (búsqueda por nombre).
_PARAMS_TEXTO = ('producto', 'cliente', 'empleado', 'categoria', 'canal', 'estado')


def permitidas(contexto=None):
    return _permitidas(contexto or contexto_actual(), REGISTRO)


def catalogo_para_prompt(herramientas=None):
    """Texto del catálogo de herramientas para el prompt de selección."""
    hs = list(REGISTRO.values()) if herramientas is None else herramientas
    return "\n".join(f"- {h.code}: {h.descripcion}" for h in hs)


def sanear_params(h, params):
    params = params if isinstance(params, dict) else {}
    safe = {}
    if 'periodo' in h.params:
        rango = rango_desde_params(params)
        if rango:
            safe['periodo'] = rango
        elif params.get('periodo'):
            # Solo pasa 'periodo' si la IA lo indicó; si no, la función usa su default.
            clave = str(params['periodo']).strip().lower().replace(' ', '_')
            safe['periodo'] = _periodo(_ALIAS_PERIODO.get(clave, clave))
    if 'limite' in h.params:
        try:
            safe['limite'] = int(params.get('limite', 5))
        except Exception:
            safe['limite'] = 5
    if 'umbral' in h.params:
        try:
            safe['umbral'] = int(params.get('umbral', 5))
        except Exception:
            safe['umbral'] = 5
    for nombre in _PARAMS_TEXTO:
        if nombre in h.params and params.get(nombre) not in (None, ''):
            safe[nombre] = str(params[nombre]).strip()[:80]
    return safe


def ejecutar(code, params, contexto=None):
    """Ejecuta una herramienta con parámetros saneados, si quien pregunta puede
    usarla. None si no existe; {'denegado': True, ...} si no tiene permiso."""
    h = REGISTRO.get(code)
    if h is None:
        return None
    if not puede_usar(h, contexto or contexto_actual()):
        return {'denegado': True,
                'motivo': f'Tu usuario no tiene permiso para consultar {h.etiqueta}.'}
    return h.fn(**sanear_params(h, params))


# ── Diccionario de datos del negocio (contexto SIEMPRE presente) ──
# Documenta, en lenguaje claro, QUÉ información maneja la tienda, qué se PUEDE
# consultar (vía las herramientas) y qué es SENSIBLE y NUNCA se entrega.
# Por seguridad la IA no ejecuta SQL: solo elige herramientas; aun así este
# contexto la orienta y le marca límites explícitos.
CONTEXTO_DATOS = """MAPA DE DATOS DEL NEGOCIO (lo que puedes saber de esta tienda):
- Catálogo: productos (nombre, precio, stock, categoría, descripción) y categorías.
- Ventas por 3 canales: tienda web (pedidos pagados), POS de mostrador (web) y
  POS de escritorio (app). Cuando hables de "ventas" considera los 3 canales.
- Clientes registrados, pedidos y su estado de envío, inventario y su valor.

QUÉ PUEDES CONSULTAR: solo a través de tus herramientas. Si no hay una
herramienta para algo, dilo con honestidad; NO inventes datos ni cifras.

DATOS SENSIBLES — NUNCA los entregues ni intentes consultarlos: contraseñas o
hashes, datos de tarjetas o medios de pago, tokens/credenciales/llaves API,
documentos de identidad completos, ni datos personales privados de un cliente.
Si te los piden, niégate amablemente y ofrece lo que sí puedes mostrar.

REGLA DE PERÍODOS: 'hoy', 'esta semana', 'este mes' y 'este año' son rangos del
calendario actual; 'la semana pasada' y 'el mes pasado' son los anteriores
completos. Si un período da 0 ventas pero el negocio tiene ventas históricas,
acláralo (no afirmes que "nunca ha vendido").

REGLA DE CONFIABILIDAD: las tendencias y los segmentos traen el campo
'confiabilidad'. Si es 'baja' o 'insuficiente', dilo claramente y NO hagas
proyecciones ni afirmaciones fuertes; explica la conclusión en palabras simples
(no hace falta nombrar R² ni k-means salvo que te lo pregunten).

REGLA DE PERMISOS: si un dato viene con 'denegado', explica que el usuario no
tiene permiso para esa información; no la inventes ni la estimes."""
