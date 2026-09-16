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
from services.ia_datos import caja as _caj
from services.ia_datos import comercial as _com
from services.ia_datos import finanzas as _fin
from services.ia_datos import inventario as _inv
from services.ia_datos import nomina as _nom
from services.ia_datos import operacion as _ope
from services.ia_datos import restaurante as _res
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
          "Cuánto vale TODO el inventario y cuántas unidades hay en total (sin distinguir si rotan o no).",
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
registrar('patron_horario', _ven.patron_horario,
          "A qué horas y qué días de la semana se vende más o menos.",
          ['periodo'], etiqueta='tus horas y días de más venta', dominio='ventas')

# ── Dinero (requieren módulo y permiso) ───────────────────────
registrar('finanzas_periodo', _fin.finanzas_periodo,
          "Ingresos, egresos y UTILIDAD (ganancia) de un período, con los gastos por concepto y la comparación con el período anterior.",
          ['periodo'], etiqueta='tus ingresos, gastos y utilidad', dominio='finanzas',
          modulos=('accounting',), permiso='accounting')
registrar('margenes_productos', _fin.margenes_productos,
          "Cuánto deja cada producto (precio menos costo): los más y menos rentables y los vendidos por debajo del costo.",
          ['periodo', 'limite'], etiqueta='el margen de tus productos', dominio='finanzas',
          permiso='accounting')
registrar('caja_estado', _caj.caja_estado,
          "Estado de la caja: turno abierto, cuánto efectivo debería haber y los últimos cuadres con faltantes o sobrantes.",
          [], etiqueta='el estado de tu caja', dominio='caja',
          modulos=('caja',), permiso='caja')
registrar('metodos_pago', _caj.metodos_pago,
          "Con qué le pagan los clientes: efectivo, tarjeta, transferencias, y cuánto pesa cada medio.",
          ['periodo'], etiqueta='tus medios de pago', dominio='caja', permiso='pos')
registrar('restaurante_ahora', _res.restaurante_ahora,
          "Cómo está el salón AHORA: mesas ocupadas o libres, cuentas abiertas, cuánto llevan consumido y cuáles se demoran.",
          [], etiqueta='el estado de tus mesas', dominio='restaurante',
          modulos=('restaurant_tables',), permiso='restaurant_tables')
registrar('restaurante_desempeno', _res.restaurante_desempeno,
          "Cómo le fue al restaurante en un período: mesas atendidas, ticket por mesa y por persona, duración, horas pico, platos más pedidos y anulaciones.",
          ['periodo'], etiqueta='el desempeño de tu restaurante', dominio='restaurante',
          modulos=('restaurant_tables',), permiso='restaurant_tables')

# ── Comercial (CRM, cotizaciones, clientes, reseñas) ──────────
registrar('crm_pipeline', _com.crm_pipeline,
          "Negocios y oportunidades en curso del CRM: cuánto hay por etapa, cuánto se espera cerrar, ganados y perdidos, y qué cierra pronto.",
          [], etiqueta='tus negocios en curso', dominio='comercial',
          modulos=('crm',), permiso='crm')
registrar('crm_seguimiento', _com.crm_seguimiento,
          "A quién hay que atender hoy: tareas vencidas o del día por responsable y clientes sin contacto hace más de un mes.",
          [], etiqueta='tus tareas y seguimientos', dominio='comercial',
          modulos=('crm',), permiso='crm')
registrar('cotizaciones_estado', _com.cotizaciones_estado,
          "Cotizaciones de un período: cuántas, por cuánto, cuántas se aprobaron y cuáles llevan días sin respuesta.",
          ['periodo'], etiqueta='tus cotizaciones', dominio='comercial',
          modulos=('quotes',), permiso='quotes')
registrar('cuentas_cobro_periodo', _com.cuentas_cobro_periodo,
          "Cuentas de cobro emitidas en un período y a qué clientes.",
          ['periodo'], etiqueta='tus cuentas de cobro', dominio='comercial',
          modulos=('billing',), permiso='billing')
registrar('cliente_historial', _com.cliente_historial,
          "Historial de compras de UN cliente por su nombre: cuántas veces compró, cuánto, cuándo fue la última vez y qué se lleva.",
          ['cliente'], etiqueta='el historial de ese cliente', dominio='clientes',
          permiso='orders')
registrar('resenas_estado', _com.resenas_estado,
          "Reseñas de los clientes: calificación promedio, cuáles faltan por aprobar o responder y los productos peor calificados.",
          [], etiqueta='las reseñas de tus clientes', dominio='comercial',
          permiso='content')

# ── Operación (inventario, pedidos, soporte, facturación) ─────
registrar('inventario_sin_rotacion', _ope.inventario_sin_rotacion,
          "SOLO los productos que no se venden hace meses: cuáles son y cuánta plata está detenida o dormida en ellos.",
          [], etiqueta='los productos que no rotan', dominio='inventario',
          permiso='inventory')
registrar('movimientos_inventario', _ope.movimientos_inventario,
          "Movimientos de inventario de un período: entradas, salidas y ajustes, con sus motivos (mermas, daños, correcciones).",
          ['periodo'], etiqueta='los movimientos de tu inventario', dominio='inventario',
          permiso='inventory')
registrar('producto_detalle', _ope.producto_detalle,
          "Ficha de UN producto por su nombre: precio, stock, cuánto se vendió en 90 días, cuándo fue su última venta, si se agota pronto y cómo lo califican.",
          ['producto'], etiqueta='la ficha de ese producto', dominio='inventario',
          permiso='inventory')
registrar('pedidos_estado', _ope.pedidos_estado,
          "Pedidos de la tienda web por estado de pago y envío, y los pagados que llevan más de 48 horas sin despachar.",
          ['periodo'], etiqueta='el estado de tus pedidos', dominio='pedidos',
          permiso='orders')
registrar('soporte_estado', _ope.soporte_estado,
          "Tickets de soporte: abiertos, sin respuesta del negocio y los más antiguos.",
          [], etiqueta='tus tickets de soporte', dominio='operacion',
          modulos=('support',), permiso='support')
registrar('fe_pendiente', _ope.fe_pendiente,
          "Facturación electrónica: qué ventas ya tienen factura y cuáles no (solo consulta, no emite nada).",
          ['periodo'], etiqueta='tu facturación electrónica', dominio='operacion',
          modulos=('facturacion_electronica',), permiso='facturacion_electronica')
registrar('cupones_desempeno', _ope.cupones_desempeno,
          "Cupones de descuento: cuántos se usaron, cuánto descuento se entregó y cuáles son los más usados.",
          ['periodo'], etiqueta='tus cupones', dominio='operacion',
          modulos=('coupons',), permiso='coupons')
registrar('deseos_demanda', _ope.deseos_demanda,
          "Productos que los clientes guardan en su lista de deseos, sobre todo los agotados: demanda que se está perdiendo.",
          [], etiqueta='las listas de deseos de tus clientes', dominio='operacion',
          modulos=('wishlist',), permiso='wishlist')

# ── Nómina (SENSIBLE: solo dueño y contador, y queda auditada) ─
registrar('nomina_resumen', _nom.nomina_resumen,
          "Cuánto cuesta la nómina en un período: devengado, deducciones, neto pagado, aportes del empleador, provisiones y costo por cargo.",
          ['periodo'], etiqueta='el costo de tu nómina', dominio='nomina',
          modulos=('payroll',), permiso='payroll', sensible='nomina')
registrar('nomina_empleado', _nom.nomina_empleado,
          "Datos de pago de UN empleado por su nombre: cargo, antigüedad, salario base, su última liquidación y sus provisiones.",
          ['empleado'], etiqueta='la nómina de ese empleado', dominio='nomina',
          modulos=('payroll',), permiso='payroll', sensible='nomina')

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
    """Texto del catálogo para el prompt de selección. Las herramientas que
    piden un nombre (cliente, empleado, producto…) lo anuncian: sin eso el
    modelo elegía bien la herramienta pero llamaba sin el dato."""
    hs = list(REGISTRO.values()) if herramientas is None else herramientas
    lineas = []
    for h in hs:
        propios = [p for p in h.params if p in _PARAMS_TEXTO]
        extra = f" (requiere el parámetro «{'», «'.join(propios)}» con el nombre)" if propios else ''
        lineas.append(f"- {h.code}: {h.descripcion}{extra}")
    return "\n".join(lineas)


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
- Según el plan y el cargo de quien pregunta, también: contabilidad (ingresos,
  egresos y utilidad), costos y márgenes por producto, caja (turno, cuadres,
  medios de pago) y restaurante (mesas, tickets, horarios, platos).

QUÉ PUEDES CONSULTAR: solo a través de tus herramientas. Si no hay una
herramienta para algo, dilo con honestidad; NO inventes datos ni cifras.

DIFERENCIA IMPORTANTE: "ventas" es lo que entró por vender; "utilidad" o
"ganancia" es lo que queda después de los gastos y sale de la contabilidad. No
uses una por la otra.

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
