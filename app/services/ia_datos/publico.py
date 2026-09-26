"""Lo que el chat del SITIO PÚBLICO puede consultar.

Regla de este archivo: aquí solo entra información que cualquiera puede ver
entrando a la tienda. Nada de dinero del negocio, nada de personas.

  - Productos: los mismos que muestra el catálogo público. Si un producto está
    archivado o no es visible en la tienda, aquí tampoco aparece.
  - Servicios y datos de contacto: lo que el dueño publicó en su sitio.
  - Nunca: ventas, caja, contabilidad, nómina, pedidos, clientes ni usuarios.

Las respuestas son cortas y ya formateadas: el modelo solo las redacta.
"""

import re

from flask import current_app

from database import get_db_cursor
from helpers import formatear_moneda
from services.ia_datos.base import _columnas, _existe

LIMITE_PRODUCTOS = 6


def _mostrar_precios():
    """El dueño puede pedir que el bot no cante precios (negocios que cotizan)."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT valor FROM cliente_config WHERE clave = 'chat_publico_precios'")
            r = cur.fetchone()
            if r and r['valor'] is not None:
                return str(r['valor']).strip().lower() not in ('false', '0', 'no', 'off')
    except Exception:
        pass
    return True


def _sql_visibles(cur, alias='p'):
    """Mismas reglas que el catálogo público (routes/public.py)."""
    cols = _columnas(cur, 'productos')
    condiciones = []
    if 'active' in cols:
        condiciones.append(f'COALESCE({alias}.active, TRUE)')
    if 'visible_en_ecommerce' in cols:
        condiciones.append(f'COALESCE({alias}.visible_en_ecommerce, TRUE)')
    return ' AND '.join(condiciones) if condiciones else 'TRUE'


def _url_producto(r):
    return f"/producto/{r['id']}-{r['slug']}" if r.get('slug') else f"/producto/{r['id']}"


_RELLENO_BUSQUEDA = {
    'para', 'con', 'sin', 'del', 'los', 'las', 'una', 'uno', 'unos', 'unas', 'que', 'por',
    'tienen', 'tienes', 'venden', 'vendes', 'hay', 'algun', 'alguna', 'algunos', 'algunas',
    'busco', 'necesito', 'quiero', 'mi', 'mis', 'este', 'esta', 'ese', 'esa', 'como',
}
_SIN_TILDES = ('áéíóúüñ', 'aeiouun')


def _singular(palabra):
    """«cargadores» → «cargador», «portátiles» → «portatil», «mouses» → «mouse»."""
    if len(palabra) > 5 and palabra.endswith('es') and palabra[-3] not in 'aeiou':
        return palabra[:-2]
    if len(palabra) > 4 and palabra.endswith('s'):          # «asus» se queda igual
        return palabra[:-1]
    return palabra


def _palabras_clave(termino):
    """Las palabras con las que buscar, sin tildes ni relleno. Solo si son
    varias o si la única cambió al pasarla a singular: si no, la frase exacta
    ya hizo la misma búsqueda."""
    from services.ia.enrutador import normalizar
    crudas = [p for p in re.split(r'[^a-z0-9]+', normalizar(termino)) if p]
    palabras = [_singular(p) for p in crudas if len(p) >= 3 and p not in _RELLENO_BUSQUEDA]
    if not palabras or (len(palabras) == 1 and crudas == palabras):
        return []
    return palabras[:5]


def _buscar_por_palabras(cur, palabras, limite, slug):
    """Segunda pasada cuando la frase exacta no encontró nada: cada palabra debe
    aparecer (sin importar tildes ni mayúsculas) en el nombre, la categoría o la
    descripción. Todas, no alguna: mejor «no lo encontré» que ofrecer otro producto."""
    campo = ("translate(lower(p.nombre || ' ' || COALESCE(g.nombre, '') || ' ' || "
             "COALESCE(p.descripcion, '')), %s, %s)")
    condiciones = ' AND '.join(f'{campo} LIKE %s' for _ in palabras)
    params = []
    for palabra in palabras:
        params += [*_SIN_TILDES, f'%{palabra}%']
    cur.execute(f"""
        SELECT p.id, p.nombre, p.precio, COALESCE(p.stock, 0) AS stock,
               COALESCE(g.nombre, '') AS categoria, {slug} AS slug
        FROM productos p LEFT JOIN generos g ON g.id = p.genero_id
        WHERE {_sql_visibles(cur)} AND {condiciones}
        ORDER BY (COALESCE(p.stock, 0) > 0) DESC, p.nombre
        LIMIT %s
    """, (*params, limite))
    return cur.fetchall()


def buscar_productos(texto='', limite=LIMITE_PRODUCTOS, **_):
    """Busca en el catálogo público por nombre o categoría."""
    termino = (texto or '').strip()
    try:
        limite = max(1, min(int(limite or LIMITE_PRODUCTOS), 10))
    except (TypeError, ValueError):
        limite = LIMITE_PRODUCTOS
    if len(termino) < 2:
        return {'conclusion': 'Dime qué producto buscas y lo reviso en el catálogo.'}

    con_precio = _mostrar_precios()
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'productos'):
            return {'conclusion': 'Esta tienda todavía no tiene catálogo publicado.'}
        cols = _columnas(cur, 'productos')
        slug = 'p.slug' if 'slug' in cols else 'NULL'
        patron = f'%{termino}%'
        cur.execute(f"""
            SELECT p.id, p.nombre, p.precio, COALESCE(p.stock, 0) AS stock,
                   COALESCE(g.nombre, '') AS categoria, {slug} AS slug
            FROM productos p LEFT JOIN generos g ON g.id = p.genero_id
            WHERE {_sql_visibles(cur)}
              AND (p.nombre ILIKE %s OR COALESCE(g.nombre, '') ILIKE %s
                   OR COALESCE(p.descripcion, '') ILIKE %s)
            ORDER BY (COALESCE(p.stock, 0) > 0) DESC, p.nombre
            LIMIT %s
        """, (patron, patron, patron, limite))
        filas = cur.fetchall()
        palabras = _palabras_clave(termino)
        if not filas and palabras:
            filas = _buscar_por_palabras(cur, palabras, limite, slug)

    if not filas:
        return {'buscado': termino,
                'conclusion': f'No encontré «{termino}» en el catálogo. '
                              'Puede que lo tengamos sin publicar: pregúntanos y te confirmamos.'}
    productos = []
    for r in filas:
        item = {'producto': r['nombre'], 'categoria': r['categoria'] or None,
                'disponible': bool(r['stock'] and r['stock'] > 0), 'enlace': _url_producto(r)}
        if con_precio and r['precio'] is not None:
            item['precio'] = formatear_moneda(float(r['precio']))
        productos.append(item)
    return {'buscado': termino, 'encontrados': len(productos), 'productos': productos,
            'nota': 'Los precios y la disponibilidad son los del catálogo en este momento.'}


def categorias(**_):
    """Qué tipos de producto maneja la tienda."""
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'generos'):
            return {'conclusion': 'Esta tienda todavía no tiene categorías publicadas.'}
        cur.execute(f"""
            SELECT g.nombre, COUNT(p.id) AS n
            FROM generos g
            LEFT JOIN productos p ON p.genero_id = g.id AND {_sql_visibles(cur)}
            GROUP BY g.id, g.nombre HAVING COUNT(p.id) > 0
            ORDER BY n DESC, g.nombre LIMIT 20
        """)
        filas = cur.fetchall()
    if not filas:
        return {'conclusion': 'Esta tienda todavía no tiene productos publicados.'}
    return {'categorias': [{'categoria': r['nombre'], 'productos': int(r['n'])} for r in filas],
            'enlace': '/productos'}


def servicios(**_):
    """Servicios que presta el negocio, tal como los publicó."""
    try:
        from services.public_site_service import get_home_services
        items = get_home_services() or []
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f'chat público: servicios ({exc})')
        items = []
    if not items:
        return {'conclusion': 'Este negocio no tiene servicios publicados en su sitio.'}
    return {'servicios': [{'servicio': s.get('titulo'), 'descripcion': s.get('descripcion'),
                           'incluye': s.get('beneficios') or None}
                          for s in items if s.get('titulo')][:8],
            'enlace': '/servicios'}


# Claves de cliente_config que sí son públicas: están en el pie de página del
# sitio. El horario lo agrega el dueño desde su panel (chat del sitio).
_CAMPOS_NEGOCIO = (
    ('empresa_nombre', 'negocio'), ('empresa_direccion', 'direccion'),
    ('empresa_telefono', 'telefono'), ('empresa_whatsapp', 'whatsapp'),
    ('empresa_email', 'correo'), ('empresa_website', 'sitio_web'),
    ('empresa_horario', 'horario'),
)


def datos_del_negocio(**_):
    """Dirección, teléfono, WhatsApp, correo y horario: lo que ya está en el pie
    del sitio. Nada que no pueda leer cualquiera que entre."""
    valores = {}
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT clave, valor FROM cliente_config WHERE clave = ANY(%s)",
                        ([c for c, _ in _CAMPOS_NEGOCIO],))
            crudos = {r['clave']: (r['valor'] or '').strip() for r in cur.fetchall()}
        valores = {nombre: crudos[clave] for clave, nombre in _CAMPOS_NEGOCIO
                   if crudos.get(clave)}
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f'chat público: datos del negocio ({exc})')

    if not valores:
        return {'conclusion': 'No tengo los datos de contacto publicados; escríbenos por el '
                              'formulario de contacto del sitio.'}
    salida = dict(valores)
    salida['enlace'] = '/contactenos'
    if 'horario' not in salida:
        salida['nota_horario'] = ('El horario no está publicado. Si te preguntan por él, '
                                  'invita a escribir por WhatsApp o al formulario de contacto.')
    return salida


def como_comprar(**_):
    """Cómo se compra en este sitio: si hay tienda en línea o es por contacto."""
    tienda = True
    try:
        from services.public_site_service import is_public_section_enabled
        tienda = bool(is_public_section_enabled('mostrar_modulo_ventas', True))
    except Exception:
        pass
    if tienda:
        return {
            'como_comprar': 'Se puede comprar en línea desde el catálogo del sitio.',
            'pasos': ['Buscar el producto en el catálogo', 'Agregarlo al carrito',
                      'Ir al carrito y completar el pago'],
            'enlace': '/productos',
            'nota': 'Las formas de pago y los envíos los responde la sección de preguntas '
                    'frecuentes del negocio, si la tiene publicada.',
        }
    return {
        'como_comprar': 'Este sitio no vende en línea: la compra se coordina con el negocio.',
        'enlace': '/contactenos',
    }
