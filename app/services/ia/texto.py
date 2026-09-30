"""Utilidades de texto compartidas por el asistente.

- palabras(): buscar registros por las palabras que usó la persona, sin tildes,
  sin relleno y en singular (buscador de las acciones y consultas de lectura).
- valores(): las cifras de un texto por su VALOR, para que los validadores
  comparen «$ 905.500,00» (formato colombiano) con «$905.500» o con el 905500.0
  de un JSON. Antes se comparaban los dígitos pegados («90550000» ≠ «905500») y
  se descartaban redacciones correctas: medido con Qwen, 10 de 10 en el panel.
"""
import re
import unicodedata
from decimal import Decimal, InvalidOperation

# Para comparar sin tildes en SQL: translate(lower(x), SIN_TILDES[0], SIN_TILDES[1]).
SIN_TILDES = ('áéíóúüñ', 'aeiouun')

_RELLENO = {
    'de', 'del', 'la', 'el', 'los', 'las', 'un', 'una', 'unos', 'unas', 'y', 'o', 'en', 'a',
    'al', 'con', 'para', 'por', 'que', 'mi', 'mis', 'su', 'sus', 'este', 'esta', 'ese', 'esa',
    'contacto', 'contactos', 'registro', 'id', 'llamado', 'llamada', 'nombre', 'se', 'llama',
}


def normalizar(texto):
    plano = unicodedata.normalize('NFD', str(texto or '').lower())
    return ''.join(c for c in plano if unicodedata.category(c) != 'Mn')


def singular(palabra):
    """«cargadores» → «cargador», «proveedores» → «proveedor»; «asus» se queda igual."""
    if len(palabra) > 5 and palabra.endswith('es') and palabra[-3] not in 'aeiou':
        return palabra[:-2]
    if len(palabra) > 4 and palabra.endswith('s'):
        return palabra[:-1]
    return palabra


def palabras(texto, relleno=()):
    """Las palabras con las que buscar: sin tildes, sin relleno y en singular.
    Conserva correos y números tal cual («ana@correo.com», «3001234567»)."""
    crudas = re.findall(r'[a-z0-9@._+-]+', normalizar(texto))
    quitar = _RELLENO | set(relleno)
    salida = []
    for p in crudas:
        p = p.strip('.-_')
        if len(p) < 2 or p in quitar:
            continue
        salida.append(p if ('@' in p or p.isdigit()) else singular(p))
    return salida[:6]


# ── Cifras por su valor ────────────────────────────────────────
_CIFRA = re.compile(r'(?<![\w.,])\d[\d.,]*\d|(?<![\w.,])\d')
# «1. Gaseosa», «2) Arepa», «- 3.» al inicio de renglón: numeración de una lista.
_VINETA = re.compile(r'(?m)^[\s>*\-•]*\**\d{1,2}[.)]\**\s')
_COLOMBIANO = re.compile(r'\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+,\d+')
_INGLES = re.compile(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d+')


def _canonico(numero):
    try:
        return format(Decimal(numero).normalize(), 'f')
    except (InvalidOperation, ValueError):
        return None


def lecturas(cifra):
    """Los valores posibles de una cifra escrita: «905.500,00» → {'905500'};
    «905500.0» → {'905500'}; «1.500» es 1500 (colombiano) o 1.5 (JSON)."""
    cifra = cifra.strip('.,')
    valores = set()
    if _COLOMBIANO.fullmatch(cifra):
        valores.add(_canonico(cifra.replace('.', '').replace(',', '.')))
    if _INGLES.fullmatch(cifra):
        valores.add(_canonico(cifra.replace(',', '')))
    if not valores:
        valores.add(_canonico(re.sub(r'\D', '', cifra)))
    return {v for v in valores if v is not None}


def cifras(texto, sin_vinetas=True):
    """Cada cifra del texto con sus lecturas posibles."""
    texto = str(texto or '')
    if sin_vinetas:
        texto = _VINETA.sub(' ', texto)
    return [lecturas(c) for c in _CIFRA.findall(texto)]


def valores(texto, sin_vinetas=True):
    """Todos los valores posibles de las cifras del texto."""
    salida = set()
    for opciones in cifras(texto, sin_vinetas):
        salida |= opciones
    return salida


_MULTIPLO = re.compile(r'(\d[\d.,]*)\s*(mil|k|millones|millon|palos?|lucas?)\b')
_FACTOR = {'mil': 1000, 'k': 1000, 'lucas': 1000, 'luca': 1000,
           'millon': 1_000_000, 'millones': 1_000_000, 'palo': 1_000_000, 'palos': 1_000_000}


def valores_dichos(texto):
    """Valores de las cifras del texto, incluidos «3 mil» = 3000, «2,5 millones»,
    «12k» o «20 lucas». Para verificar precios y cantidades dichas por la persona."""
    texto = normalizar(texto)
    salida = valores(texto, sin_vinetas=False)
    for cifra, palabra in _MULTIPLO.findall(texto):
        for lectura in lecturas(cifra):
            canonico = _canonico(Decimal(lectura) * _FACTOR[palabra])
            if canonico:
                salida.add(canonico)
    return salida


def valor_dicho(valor, fuentes):
    """¿El número (del JSON del modelo) coincide en valor con uno dicho?"""
    if isinstance(valor, bool) or valor is None:
        return False
    if isinstance(valor, (int, float)):
        opciones = {_canonico(repr(valor))} - {None}
    else:
        opciones = lecturas(str(valor).strip().lstrip('$').strip())
    return bool(opciones) and any(opciones & valores_dichos(f) for f in fuentes)


def cifras_respaldadas(texto, fuente):
    """¿Cada cifra del texto coincide en valor con alguna de la fuente?"""
    disponibles = valores(fuente, sin_vinetas=False)
    return all(opciones & disponibles for opciones in cifras(texto))
