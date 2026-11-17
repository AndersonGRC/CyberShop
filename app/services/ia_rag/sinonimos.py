"""Sinónimos propios de cada tienda para la búsqueda de la IA.

La lista de services/ia_rag/buscar.py (SINONIMOS) es la misma para todos los
negocios: «abren» = «horario atención». Cada tienda tiene además su forma de
hablar («almuerzo» = «menú corrientazo», «pola» = «cerveza»). Aquí la escribe
el negocio, una línea por palabra:

    almuerzo = menu corrientazo ejecutivo
    pola = cerveza

Se guarda en cliente_config (clave `ia_sinonimos`) de la BD de ESA tienda: no
se mezcla con las de otros clientes. Cada cambio queda en la bitácora de la
base de conocimiento y se puede deshacer.

Se aplica igual que los sinónimos comunes: solo a la pregunta (nunca al texto
del negocio) y solo en la búsqueda permisiva.
"""
import re
import time
import unicodedata

from database import _current_db_name, get_db_cursor

CLAVE = 'ia_sinonimos'
MAX_LINEAS = 100
MAX_EQUIVALENTES = 120
_TTL_S = 60
_CACHE = {}                 # BD -> (instante, {palabra: equivalentes})


def _plano(texto):
    sin = unicodedata.normalize('NFD', str(texto or '').lower())
    return ''.join(c for c in sin if unicodedata.category(c) != 'Mn')


def _palabras(texto):
    return re.findall(r'[a-z0-9ñ]+', _plano(texto))


def parsear(texto):
    """({palabra: 'equivalentes'}, [errores]). Acepta «=» o «:» como separador."""
    tabla, errores = {}, []
    lineas = [l.strip() for l in str(texto or '').splitlines()]
    lineas = [l for l in lineas if l and not l.startswith('#')]
    if len(lineas) > MAX_LINEAS:
        errores.append(f'Máximo {MAX_LINEAS} líneas.')
        lineas = lineas[:MAX_LINEAS]
    for n, linea in enumerate(lineas, 1):
        if '=' in linea:
            clave, valor = linea.split('=', 1)
        elif ':' in linea:
            clave, valor = linea.split(':', 1)
        else:
            errores.append(f'Línea {n} («{linea[:40]}»): escribe «palabra = equivalentes».')
            continue
        claves = _palabras(clave)
        equivalentes = ' '.join(_palabras(valor))[:MAX_EQUIVALENTES].strip()
        if len(claves) != 1:
            errores.append(f'Línea {n}: «{clave.strip()[:40]}» debe ser una sola palabra.')
            continue
        if not equivalentes:
            errores.append(f'Línea {n}: falta qué significa «{claves[0]}».')
            continue
        previo = tabla.get(claves[0])
        tabla[claves[0]] = f'{previo} {equivalentes}'.strip() if previo else equivalentes
    return tabla, errores


def como_texto(tabla):
    return '\n'.join(f'{k} = {v}' for k, v in sorted(tabla.items()))


def leer_texto():
    """El texto guardado de esta tienda ('' si no hay)."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT valor FROM cliente_config WHERE clave = %s ORDER BY 1 LIMIT 1',
                        (CLAVE,))
            fila = cur.fetchone()
            return (fila['valor'] if fila else '') or ''
    except Exception:  # noqa: BLE001
        return ''


def de_la_tienda():
    """{palabra: equivalentes} de esta tienda, con caché corta. Nunca lanza."""
    clave = _current_db_name()
    guardado = _CACHE.get(clave)
    if guardado and time.time() - guardado[0] < _TTL_S:
        return guardado[1]
    tabla, _errores = parsear(leer_texto())
    _CACHE[clave] = (time.time(), tabla)
    return tabla


def guardar(texto, origen='panel', accion='editar'):
    """Valida y guarda. Devuelve la tabla; ValueError con los errores."""
    from services.config_tenant import set_cliente_config
    from services.ia_rag import bitacora
    tabla, errores = parsear(texto)
    if errores:
        raise ValueError(' '.join(errores[:5]))
    nuevo = como_texto(tabla)
    antes = leer_texto()
    if nuevo == antes.strip():
        return tabla
    with get_db_cursor() as cur:
        set_cliente_config(cur, CLAVE, nuevo, grupo='ia',
                           descripcion='Sinónimos de la IA (búsqueda del chat y del asistente)')
    _CACHE.pop(_current_db_name(), None)
    bitacora.registrar('sinonimos', accion, CLAVE, 'Sinónimos de la IA',
                       antes={'texto': antes}, despues={'texto': nuevo}, origen=origen)
    return tabla
