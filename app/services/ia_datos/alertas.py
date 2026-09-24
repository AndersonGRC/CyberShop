"""Alertas del negocio: lo que conviene atender hoy.

Se calculan con consultas y reglas en Python, SIN pasar por el modelo de IA: así
salen siempre, aunque el servidor de IA esté apagado, y sin gastar GPU. La IA
solo las redacta cuando se le piden en el chat o en el correo diario.

Cada alerta declara el módulo y el permiso que exige, y se filtran con las
mismas reglas del catálogo (ver acceso.py). La nómina NO genera alertas: es
información sensible y no debe aparecer en un panel compartido ni en un correo.
"""

import time

from database import _current_db_name, get_db_cursor
from helpers import formatear_moneda
from tenant_features import get_current_tenant_id

from services.ia_datos.acceso import Contexto, puede_usar
from services.ia_datos.base import _PEDIDO_PAGADO, _columnas, _existe

_CACHE = {}
_CACHE_TTL = 600           # 10 min: el dashboard se abre muchas veces seguidas

NIVELES = ('alta', 'media', 'info')


class _Regla:
    """Mínimo compatible con puede_usar(): módulo del plan y permiso del rol."""

    def __init__(self, modulos=(), permiso=None):
        self.modulos = modulos
        self.permiso = permiso
        self.sensible = None


def _alerta(codigo, nivel, titulo, detalle, enlace=None, modulos=(), permiso=None):
    return {'codigo': codigo, 'nivel': nivel, 'titulo': titulo, 'detalle': detalle,
            'enlace': enlace, '_regla': _Regla(modulos, permiso)}


def _stock(cur):
    fuera = []
    cur.execute("SELECT COUNT(*) AS n FROM productos WHERE stock <= 0")
    agotados = int(cur.fetchone()['n'] or 0)
    if agotados:
        fuera.append(_alerta('agotados', 'alta', f'{agotados} producto(s) agotados',
                             'No puedes venderlos hasta reponerlos.', '/admin/inventario',
                             permiso='inventory'))
    if 'stock_minimo' in _columnas(cur, 'productos'):
        cur.execute("""SELECT COUNT(*) AS n FROM productos
                       WHERE stock > 0 AND COALESCE(stock_minimo, 0) > 0 AND stock <= stock_minimo""")
        bajos = int(cur.fetchone()['n'] or 0)
        if bajos:
            fuera.append(_alerta('bajo_minimo', 'media', f'{bajos} producto(s) por debajo de su mínimo',
                                 'Conviene pedirlos antes de que se agoten.', '/admin/inventario',
                                 permiso='inventory'))
    return fuera


def _ventas_de_ayer(cur):
    """¿Ayer se vendió mucho menos (o más) de lo normal para ese día de la semana?"""
    from services import estadistica as est
    partes = [f"SELECT DATE(fecha_creacion) d, monto_total t FROM pedidos WHERE {_PEDIDO_PAGADO}"]
    if _existe(cur, 'ventas_pos'):
        partes.append("SELECT DATE(fecha), total FROM ventas_pos WHERE COALESCE(estado,'completada') <> 'anulada'")
    if _existe(cur, 'pos_desktop_sales'):
        partes.append("SELECT DATE(created_at_local), total FROM pos_desktop_sales")
    union = ' UNION ALL '.join(partes)
    # Mismo día de la semana en los últimos dos meses. Ayer va aparte: si no hubo
    # ventas no aparece en el GROUP BY y compararíamos contra el martes equivocado.
    cur.execute(f"""SELECT d, SUM(t) AS total FROM ({union}) x
                    WHERE d >= CURRENT_DATE - 60 AND d < CURRENT_DATE - 1
                      AND EXTRACT(ISODOW FROM d) = EXTRACT(ISODOW FROM CURRENT_DATE - 1)
                    GROUP BY d ORDER BY d""")
    historico = [float(r['total'] or 0) for r in cur.fetchall()]
    if len(historico) < 6:
        return []
    cur.execute(f"""SELECT COALESCE(SUM(t), 0) AS total FROM ({union}) x WHERE d = CURRENT_DATE - 1""")
    ayer = float(cur.fetchone()['total'] or 0)
    z = est.z_score(ayer, historico)
    if z is None:
        return []
    promedio = sum(historico) / len(historico)
    if z <= -2:
        return [_alerta('ventas_bajas', 'alta', 'Las ventas de ayer estuvieron muy por debajo de lo normal',
                        f'Ayer vendiste {formatear_moneda(ayer)} y para ese día sueles vender cerca de '
                        f'{formatear_moneda(promedio)}.', '/admin/contabilidad/ventas')]
    if z >= 2:
        return [_alerta('ventas_altas', 'info', 'Ayer vendiste bastante más de lo normal',
                        f'Ayer vendiste {formatear_moneda(ayer)} frente a unos {formatear_moneda(promedio)} '
                        'habituales. Revisa si puedes repetirlo.', '/admin/contabilidad/ventas')]
    return []


def _pedidos(cur):
    cur.execute("""SELECT COUNT(*) AS n FROM pedidos WHERE estado_pago = 'APROBADO'
                   AND estado_envio IN ('POR_DESPACHAR', 'PENDIENTE')
                   AND fecha_creacion < NOW() - INTERVAL '48 hours'""")
    n = int(cur.fetchone()['n'] or 0)
    return [_alerta('pedidos_atrasados', 'alta', f'{n} pedido(s) pagados sin despachar',
                    'Llevan más de 48 horas esperando.', '/admin/pedidos', permiso='orders')] if n else []


def _caja(cur):
    if not _existe(cur, 'caja_sesiones'):
        return []
    fuera = []
    cur.execute("""SELECT fecha_apertura, EXTRACT(EPOCH FROM (NOW() - fecha_apertura)) / 3600 AS horas
                   FROM caja_sesiones WHERE estado = 'abierta' ORDER BY id DESC LIMIT 1""")
    abierta = cur.fetchone()
    if abierta and float(abierta['horas'] or 0) >= 14:
        fuera.append(_alerta('caja_sin_cerrar', 'media', 'La caja lleva mucho tiempo abierta',
                             f"Abierta hace {int(abierta['horas'])} horas. Conviene cuadrarla y cerrarla.",
                             '/admin/caja', modulos=('caja',), permiso='caja'))
    cur.execute("""SELECT diferencia, fecha_cierre FROM caja_sesiones
                   WHERE estado <> 'abierta' AND fecha_cierre IS NOT NULL
                   ORDER BY fecha_cierre DESC LIMIT 1""")
    ultimo = cur.fetchone()
    if ultimo and abs(float(ultimo['diferencia'] or 0)) >= 1:
        dif = float(ultimo['diferencia'])
        fuera.append(_alerta('caja_descuadrada', 'media',
                             f"El último cierre de caja quedó con {'sobrante' if dif > 0 else 'faltante'}",
                             f"Diferencia de {formatear_moneda(abs(dif))} el "
                             f"{ultimo['fecha_cierre'].date().isoformat()}.",
                             '/admin/caja', modulos=('caja',), permiso='caja'))
    return fuera


def _restaurante(cur):
    if not _existe(cur, 'restaurant_table_orders'):
        return []
    cur.execute("""SELECT COUNT(*) AS n, COALESCE(SUM(total_acumulado), 0) AS total
                   FROM restaurant_table_orders
                   WHERE estado = 'abierta' AND opened_at < NOW() - INTERVAL '3 hours'""")
    r = cur.fetchone()
    n = int(r['n'] or 0)
    return [_alerta('mesas_demoradas', 'media', f'{n} mesa(s) llevan más de 3 horas abiertas',
                    f"Suman {formatear_moneda(float(r['total'] or 0))} sin cobrar.",
                    '/admin/salon', modulos=('restaurant_tables',), permiso='restaurant_tables')] if n else []


def _crm(cur):
    fuera = []
    if _existe(cur, 'crm_tareas'):
        cur.execute("""SELECT COUNT(*) AS n FROM crm_tareas
                       WHERE estado = 'pendiente' AND fecha_limite < CURRENT_DATE""")
        n = int(cur.fetchone()['n'] or 0)
        if n:
            fuera.append(_alerta('tareas_vencidas', 'media', f'{n} tarea(s) del CRM vencidas',
                                 'Hay compromisos con clientes sin cumplir.', '/admin/crm/tareas',
                                 modulos=('crm',), permiso='crm'))
    if _existe(cur, 'crm_oportunidades'):
        cur.execute("""SELECT COUNT(*) AS n, COALESCE(SUM(monto_estimado), 0) AS total
                       FROM crm_oportunidades
                       WHERE etapa IN ('prospecto','calificado','propuesta','negociacion')
                         AND fecha_cierre_est BETWEEN CURRENT_DATE AND CURRENT_DATE + 7""")
        r = cur.fetchone()
        if int(r['n'] or 0):
            fuera.append(_alerta('cierres_semana', 'info', f"{int(r['n'])} negocio(s) deberían cerrarse esta semana",
                                 f"Suman {formatear_moneda(float(r['total'] or 0))}.", '/admin/crm/pipeline',
                                 modulos=('crm',), permiso='crm'))
    return fuera


def _cotizaciones(cur):
    if not _existe(cur, 'cotizaciones'):
        return []
    estado = ("COALESCE(NULLIF(TRIM(estado), ''), 'pendiente')"
              if 'estado' in _columnas(cur, 'cotizaciones') else "'pendiente'")
    cur.execute(f"""SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS total FROM cotizaciones
                    WHERE {estado} = 'pendiente' AND fecha < CURRENT_DATE - 15""")
    r = cur.fetchone()
    n = int(r['n'] or 0)
    return [_alerta('cotizaciones_frias', 'info', f'{n} cotización(es) llevan más de 15 días sin respuesta',
                    f"Suman {formatear_moneda(float(r['total'] or 0))}. Una llamada puede cerrarlas.",
                    '/admin/cotizar', modulos=('quotes',), permiso='quotes')] if n else []


def _cartera(cur):
    """Cobros vencidos: aprobado, registrado en contabilidad y sin desembolsar.

    Solo aplica a los negocios que ya llevan el estado de cobro (migración 0011).
    """
    fuera = []
    plazo = "COALESCE(fecha_vencimiento, (fecha + INTERVAL '30 days'))::date"
    for tabla, etiqueta, filtro in (
            ('cuentas_cobro', 'cuenta(s) de cobro', 'TRUE'),
            ('cotizaciones', 'cotización(es) aprobada(s)', "COALESCE(estado, 'pendiente') = 'aprobada'")):
        if not (_existe(cur, tabla) and 'estado_pago' in _columnas(cur, tabla)):
            continue
        cur.execute(f"""SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS total,
                               MAX(CURRENT_DATE - {plazo}) AS mora
                        FROM {tabla}
                        WHERE {filtro} AND estado_pago = 'pendiente' AND {plazo} < CURRENT_DATE""")
        r = cur.fetchone()
        n = int(r['n'] or 0)
        if n:
            fuera.append(_alerta(f'cartera_vencida_{tabla}', 'media',
                                 f'{n} {etiqueta} vencida(s) sin cobrar',
                                 f"Suman {formatear_moneda(float(r['total'] or 0))} y la más atrasada "
                                 f"lleva {int(r['mora'] or 0)} día(s).",
                                 '/admin/cuenta_cobro/cartera',
                                 modulos=('billing',), permiso='billing'))
    return fuera


def _resenas(cur):
    if not _existe(cur, 'producto_comentarios'):
        return []
    cols = _columnas(cur, 'producto_comentarios')
    fuera = []
    cur.execute("SELECT COUNT(*) AS n FROM producto_comentarios WHERE NOT COALESCE(aprobado, FALSE)")
    n = int(cur.fetchone()['n'] or 0)
    if n:
        fuera.append(_alerta('resenas_sin_aprobar', 'info', f'{n} reseña(s) esperan aprobación',
                             'Hasta que las apruebes no se ven en la tienda.', '/admin/resenas',
                             permiso='content'))
    if 'respuesta' in cols:
        cur.execute("""SELECT COUNT(*) AS n FROM producto_comentarios
                       WHERE COALESCE(aprobado, FALSE) AND (respuesta IS NULL OR TRIM(respuesta) = '')
                         AND calificacion <= 3""")
        malas = int(cur.fetchone()['n'] or 0)
        if malas:
            fuera.append(_alerta('resenas_malas', 'media', f'{malas} reseña(s) regulares o malas sin responder',
                                 'Responder mejora la imagen del negocio y el posicionamiento.',
                                 '/admin/resenas', permiso='content'))
    return fuera


def _soporte(cur):
    if not (_existe(cur, 'tickets_soporte') and _existe(cur, 'ticket_respuestas')):
        return []
    cur.execute("""SELECT COUNT(*) AS n FROM tickets_soporte t
                   WHERE LOWER(COALESCE(t.estado, 'abierto')) <> 'cerrado'
                     AND t.fecha_creacion < NOW() - INTERVAL '48 hours'
                     AND NOT EXISTS (SELECT 1 FROM ticket_respuestas r
                                     WHERE r.ticket_id = t.id AND r.es_admin)""")
    n = int(cur.fetchone()['n'] or 0)
    return [_alerta('soporte_sin_responder', 'media', f'{n} ticket(s) de soporte sin respuesta',
                    'Llevan más de 48 horas esperando.', '/admin/soporte',
                    modulos=('support',), permiso='support')] if n else []


def _facturacion(cur):
    if not (_existe(cur, 'ventas_pos') and 'factura_dian_id' in _columnas(cur, 'ventas_pos')):
        return []
    cur.execute("""SELECT COUNT(*) AS n FROM ventas_pos
                   WHERE factura_dian_id IS NULL AND COALESCE(estado, 'completada') <> 'anulada'
                     AND fecha >= date_trunc('month', CURRENT_DATE)""")
    n = int(cur.fetchone()['n'] or 0)
    return [_alerta('ventas_sin_factura', 'media', f'{n} venta(s) de este mes sin factura electrónica',
                    'Revisa si deben facturarse antes del cierre.', '/admin/facturacion',
                    modulos=('facturacion_electronica',), permiso='facturacion_electronica')] if n else []


def _datos_incompletos(cur):
    """Sin cliente en la venta no hay segmentación posible; sin costo no hay margen."""
    from services.ia_datos.operacion import ventas_con_cliente
    fuera = []
    ident, total = ventas_con_cliente(cur, 90)
    if total >= 30 and (ident / total) < 0.2:
        fuera.append(_alerta('ventas_sin_cliente', 'info',
                             f'Solo el {ident / total * 100:.0f}% de tus ventas registra quién compró',
                             'Pedir el nombre o el documento al cobrar te permite saber quién vuelve y a quién '
                             'recuperar.', '/admin/pos', permiso='orders'))
    if 'costo' in _columnas(cur, 'productos'):
        cur.execute("""SELECT COUNT(*) FILTER (WHERE COALESCE(costo, 0) <= 0) AS sin, COUNT(*) AS total
                       FROM productos""")
        r = cur.fetchone()
        if int(r['total'] or 0) and int(r['sin'] or 0) > int(r['total']) * 0.3:
            fuera.append(_alerta('productos_sin_costo', 'info',
                                 f"{int(r['sin'])} productos no tienen costo cargado",
                                 'Sin costo no puedo calcular tu margen ni tu ganancia por producto.',
                                 '/admin/productos', permiso='inventory'))
    return fuera


_REGLAS = (_stock, _ventas_de_ayer, _pedidos, _caja, _restaurante, _crm, _cotizaciones, _cartera,
           _resenas, _soporte, _facturacion, _datos_incompletos)


def _calcular():
    alertas = []
    with get_db_cursor(dict_cursor=True) as cur:
        for regla in _REGLAS:
            try:
                alertas.extend(regla(cur) or [])
            except Exception:
                # Una regla que falle (tabla rara, columna ausente) no debe tumbar el resto.
                try:
                    cur.connection.rollback()
                except Exception:
                    pass
    return alertas


def alertas_negocio(contexto=None, refrescar=False, **_):
    """Alertas visibles para quien pregunta, ordenadas por urgencia."""
    from services.ia_datos.acceso import contexto_actual
    ctx = contexto or contexto_actual()
    clave = (_current_db_name(), get_current_tenant_id())
    guardado = _CACHE.get(clave)
    if refrescar or not guardado or time.time() > guardado[1]:
        guardado = (_calcular(), time.time() + _CACHE_TTL)
        _CACHE[clave] = guardado
    orden = {n: i for i, n in enumerate(NIVELES)}
    visibles = [a for a in guardado[0] if puede_usar(a['_regla'], ctx)]
    visibles.sort(key=lambda a: orden.get(a['nivel'], 9))
    limpias = [{k: v for k, v in a.items() if not k.startswith('_')} for a in visibles]
    return {
        'alertas': limpias,
        'cantidad': len(limpias),
        'urgentes': sum(1 for a in limpias if a['nivel'] == 'alta'),
        'nota': ('Todo en orden por ahora: no hay nada urgente que atender.' if not limpias else
                 'Calculado con los datos del negocio, sin usar el modelo de IA.'),
    }


def alertas_para_correo():
    """Alertas del negocio completo (sin filtrar por rol) para el resumen diario
    del dueño. Nunca incluye nómina: ninguna regla la consulta."""
    return alertas_negocio(contexto=Contexto(canal='sistema'), refrescar=True)
