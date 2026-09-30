"""Buscar registros como los nombra la persona, no como están escritos.

Caso real (Panadería Nicol's, 28-sep): el dueño creó el contacto «Cybershop» y
luego pidió «edita el contacto de Cybershop Proveedor Tecnológico…». Editar
exigía el nombre EXACTO o el ID y respondió «No encontré ese contacto».

Orden de búsqueda:
  1. Teléfono (7+ dígitos), correo o nombre exactos.
  2. Todas las palabras (sin tildes, en singular) en nombre, empresa, correo o
     teléfono.
  3. Las que más palabras comparten: se usa solo si hay UN candidato claro;
     si no, se devuelven las opciones para que la persona elija por ID.

Solo lee. La acción siempre muestra el registro encontrado (con su ID) en la
vista previa antes de confirmar.
"""
import re

from services.ia.texto import SIN_TILDES, palabras

_CONTACTO_COLUMNAS = ('id', 'nombre', 'tipo', 'empresa', 'cargo', 'email', 'telefono',
                      'whatsapp', 'sitio_web', 'direccion', 'ciudad', 'notas', 'origen', 'activo')
_TEXTO_CONTACTO = ("translate(lower(COALESCE(nombre,'') || ' ' || COALESCE(empresa,'') || ' ' || "
                   "COALESCE(email,'') || ' ' || COALESCE(telefono,'') || ' ' || "
                   "COALESCE(whatsapp,'')), %s, %s)")
# Palabras que dicen QUÉ es el registro, no cuál: «el proveedor Cybershop».
_TIPOS = ('proveedor', 'cliente', 'lead', 'socio', 'provedor', 'provvedor')


def _columnas():
    return ', '.join(_CONTACTO_COLUMNAS)


def contactos(cur, referencia, activos=True, limite=5):
    """Busca contactos por lo que dijo la persona.

    Devuelve (filas, modo): modo 'exacto' | 'todas' | 'parcial' | 'ninguno'.
    En 'parcial' cada fila trae 'puntos' (cuántas palabras coinciden) y
    'palabras' (cuántas se buscaron)."""
    ref = str(referencia or '').strip()
    if not ref:
        return [], 'ninguno'
    base = f'SELECT {_columnas()} FROM crm_contactos WHERE activo = %s'

    digitos = re.sub(r'\D', '', ref)
    if len(digitos) >= 7 and len(digitos) >= len(re.sub(r'\s', '', ref)) - 3:
        cur.execute(base + " AND (regexp_replace(COALESCE(telefono,''), '\\D', '', 'g') = %s "
                    "OR regexp_replace(COALESCE(whatsapp,''), '\\D', '', 'g') = %s) "
                    "ORDER BY id LIMIT %s", (activos, digitos, digitos, limite + 1))
        filas = [dict(f) for f in cur.fetchall()]
        if filas:
            return filas, 'exacto'

    cur.execute(base + ' AND (LOWER(nombre) = LOWER(%s) OR LOWER(COALESCE(email, \'\')) = LOWER(%s)) '
                'ORDER BY id LIMIT %s', (activos, ref, ref, limite + 1))
    filas = [dict(f) for f in cur.fetchall()]
    if filas:
        return filas, 'exacto'

    buscar = [p for p in palabras(ref) if p not in _TIPOS]
    if not buscar:
        return [], 'ninguno'
    puntos = ' + '.join(f'(CASE WHEN {_TEXTO_CONTACTO} LIKE %s THEN 1 ELSE 0 END)'
                        for _ in buscar)
    params = []
    for p in buscar:
        params += [*SIN_TILDES, f'%{p}%']
    cur.execute(f'SELECT * FROM (SELECT {_columnas()}, ({puntos}) AS puntos '
                f'FROM crm_contactos WHERE activo = %s) x WHERE puntos > 0 '
                f'ORDER BY puntos DESC, id LIMIT %s', (*params, activos, limite + 1))
    filas = [dict(f) for f in cur.fetchall()]
    if not filas:
        return [], 'ninguno'
    for f in filas:
        f['palabras'] = len(buscar)
    todas = [f for f in filas if f['puntos'] == len(buscar)]
    if todas:
        return todas, 'todas'
    return filas, 'parcial'


def contacto_mencionado(cur, texto):
    """El contacto activo cuyo nombre completo aparece escrito en la frase
    («…visité a Distribuidora Andes…»), o None si no hay uno claro. Si aparecen
    «Andes» y «Distribuidora Andes», gana el más largo que contiene al otro."""
    from services.ia.texto import normalizar
    plano = ' '.join(re.sub(r'[^a-z0-9@.]+', ' ', normalizar(texto)).split())
    cur.execute("""SELECT id, nombre FROM crm_contactos
                   WHERE activo = TRUE AND length(nombre) >= 4
                     AND %s LIKE '%%' || regexp_replace(translate(lower(nombre), %s, %s),
                                                        '[^a-z0-9@.]+', ' ', 'g') || '%%'
                   ORDER BY length(nombre) DESC LIMIT 4""", (plano, *SIN_TILDES))
    filas = [dict(f) for f in cur.fetchall()]
    if not filas:
        return None
    mayor = normalizar(filas[0]['nombre'])
    if all(normalizar(f['nombre']) in mayor for f in filas[1:]):
        return filas[0]
    return None


def elegir(filas, modo):
    """El registro a usar, o None si hay que preguntar cuál.

    - Exacto o con todas las palabras: si es uno solo.
    - Parcial: si es el ÚNICO candidato, o si su puntaje supera al segundo y
      cubre al menos la mitad de las palabras buscadas.
    """
    if not filas:
        return None
    if modo in ('exacto', 'todas'):
        return filas[0] if len(filas) == 1 else None
    if len(filas) == 1:
        return filas[0]
    primero, segundo = filas[0], filas[1]
    if primero['puntos'] > segundo['puntos'] and primero['puntos'] * 2 >= primero['palabras']:
        return primero
    return None


def _por_palabras(cur, tabla, columnas, texto_sql, filtro, filtro_params, referencia, limite,
                  ignorar=()):
    """Búsqueda por palabras con puntaje, común a productos y categorías."""
    buscar = [p for p in palabras(referencia) if p not in ignorar]
    if not buscar:
        return [], 'ninguno'
    puntos = ' + '.join(f'(CASE WHEN {texto_sql} LIKE %s THEN 1 ELSE 0 END)' for _ in buscar)
    params = []
    for p in buscar:
        params += [*SIN_TILDES, f'%{p}%']
    cur.execute(f'SELECT * FROM (SELECT {columnas}, ({puntos}) AS puntos FROM {tabla} '
                f'WHERE {filtro}) x WHERE puntos > 0 ORDER BY puntos DESC, id LIMIT %s',
                (*params, *filtro_params, limite + 1))
    filas = [dict(f) for f in cur.fetchall()]
    if not filas:
        return [], 'ninguno'
    for f in filas:
        f['palabras'] = len(buscar)
    todas = [f for f in filas if f['puntos'] == len(buscar)]
    return (todas, 'todas') if todas else (filas, 'parcial')


def productos(cur, referencia, activos=True, tiene_active=True, limite=5):
    """Productos por referencia o nombre exactos, o por palabras.
    `tiene_active=False` en bases viejas sin la columna (no se filtra)."""
    ref = str(referencia or '').strip()
    if not ref:
        return [], 'ninguno'
    columnas = 'id, nombre, referencia, precio, stock' + (', active' if tiene_active else '')
    filtro, filtro_params = ('COALESCE(active, TRUE) = %s', (activos,)) if tiene_active else ('TRUE', ())
    cur.execute(f'SELECT {columnas} FROM productos WHERE {filtro} AND '
                '(LOWER(referencia) = LOWER(%s) OR LOWER(nombre) = LOWER(%s)) ORDER BY id LIMIT %s',
                (*filtro_params, ref, ref, limite + 1))
    filas = [dict(f) for f in cur.fetchall()]
    if filas:
        return filas, 'exacto'
    texto = "translate(lower(nombre || ' ' || COALESCE(referencia, '')), %s, %s)"
    return _por_palabras(cur, 'productos', columnas, texto, filtro, filtro_params, ref, limite,
                         ignorar=('producto', 'articulo', 'item'))


def categorias(cur, referencia, limite=5):
    ref = str(referencia or '').strip()
    if not ref:
        return [], 'ninguno'
    cur.execute('SELECT id, nombre FROM generos WHERE LOWER(nombre) = LOWER(%s) ORDER BY id LIMIT %s',
                (ref, limite + 1))
    filas = [dict(f) for f in cur.fetchall()]
    if filas:
        return filas, 'exacto'
    return _por_palabras(cur, 'generos', 'id, nombre', 'translate(lower(nombre), %s, %s)',
                         'TRUE', (), ref, limite, ignorar=('categoria', 'genero', 'seccion'))


def opciones(filas, limite=5, extra=None):
    """«ID 4 · Gaseosa · REF-1» para elegir; `extra(f)` agrega un dato por fila."""
    lineas = []
    for f in filas[:limite]:
        partes = [f"ID {f['id']}", f['nombre']] + ([extra(f)] if extra else [])
        lineas.append(' · '.join(str(p) for p in partes if p not in (None, '')))
    return lineas


def opciones_contacto(filas, limite=5):
    """«ID 1 · Cybershop · proveedor · ventas@…» para que la persona elija."""
    lineas = []
    for f in filas[:limite]:
        partes = [f"ID {f['id']}", f['nombre']]
        partes += [v for v in (f.get('tipo'), f.get('email') or f.get('telefono')) if v]
        lineas.append(' · '.join(str(p) for p in partes))
    return lineas
