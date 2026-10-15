# -*- coding: utf-8 -*-
"""Servicio Técnico: versiones de la ficha técnica de cada equipo.

Cada vez que la ficha de un equipo cambia —al volver a traer su Excel o PDF,
al guardarla a mano o al editar el equipo— se guarda cómo quedó, y la primera
vez también cómo estaba antes: la versión anterior nunca se pierde. Una
importación deja UNA versión por equipo aunque el equipo venga en varias filas
(la tabla de control y su hoja). Nada se borra: deshacer la importación deja su
versión inactiva y devuelve los datos que nadie volvió a cambiar.

Lo que se guarda de cada versión: la ficha (lo que dice el documento), su
código, los datos del equipo con que se arma (marca, modelo, procesador…), sus
extras y la descripción. Fotos, documentos, mantenimientos, cambios de piezas,
órdenes y recordatorios son del equipo, no de la versión: no se tocan.
"""
import json
import re
import unicodedata

from services import servicio_tecnico_service as st
from services import servicio_tecnico_tipos as tipos

CAMPOS = st._COLUMNAS_EQUIPO + ('tipo',)
# Textos de la ficha que se comparan (además de sus filas).
TEXTOS_FICHA = (('estado', 'Estado'), ('destacar', 'Filas resaltadas'), ('asignado_a', 'Asignado a'),
                ('empresa', 'Empresa'), ('descripcion', 'Descripción'), ('problema', 'Problema'),
                ('requerimientos', 'Requerimientos'), ('vida_util', 'Vida útil'),
                ('recomendaciones', 'Recomendaciones'), ('fabricante', 'Datos del fabricante'),
                ('fabricante_detalle', 'Detalle del fabricante'))
# Lo de un computador que la plantilla del taller no muestra en sus filas.
_EXTRAS_YA_EN_FILAS = ('board', 'tipo_disco', 'ram_ranuras_total', 'ram_ranuras_libres')
ESTADOS_FICHA = {'bueno': 'En buen estado', 'inconveniente': 'Presenta inconvenientes'}
ORIGENES = {'anterior': 'Como estaba antes', 'importacion': 'Importación', 'manual': 'Cambio a mano'}


def _norm(texto):
    t = unicodedata.normalize('NFD', str(texto or '').lower())
    t = ''.join(ch for ch in t if unicodedata.category(ch) != 'Mn')
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', t).split())


def _vacio(valor):
    return valor in (None, '', [], {}) or (isinstance(valor, str) and not valor.strip())


def estado_de(equipo):
    """Lo que se guarda de un equipo en una versión (de una fila de st_equipos)."""
    return {
        'ficha': dict(equipo.get('ficha') or {}),
        'ficha_codigo': equipo.get('ficha_codigo'),
        'equipo': {c: equipo.get(c) for c in CAMPOS},
        'extras': dict(equipo.get('extras') or {}),
        'resumen': equipo.get('resumen_ia'),
    }


def numero(estado):
    """El número de versión de la ficha de ese estado (0 si aún no tenía ficha)."""
    ficha = estado.get('ficha') or {}
    if not ficha:
        return 0
    try:
        return max(1, int(ficha.get('version') or 1))
    except (TypeError, ValueError):
        return 1


def tiene_contenido(estado):
    return bool(estado.get('ficha')) or any(not _vacio(v) for c, v in (estado.get('equipo') or {}).items()
                                            if c != 'tipo')


def contenido(estado):
    """{etiqueta: texto} de lo que muestra la ficha con ese estado: sus filas
    (las propias o, si no las trae, las que salen de los datos del equipo) y sus
    textos. Es lo que se compara entre versiones."""
    from services.servicio_tecnico_ficha import filas_base
    equipo = dict(estado.get('equipo') or {})
    equipo['extras'] = estado.get('extras') or {}
    ficha = estado.get('ficha') or {}
    propias = ficha.get('filas') or {}
    salida = {}
    for etq, auto in filas_base(equipo):
        salida[etq] = str(propias.get(etq) or auto or '').strip()
    for etq, valor in propias.items():
        salida[etq] = str(valor or '').strip()
    if equipo.get('tipo') in ('computador', 'portatil'):     # lo que la plantilla del taller no muestra
        valores = {_norm(v) for v in salida.values() if v}
        sueltos = [(tipos.ETIQUETAS_COMUNES[c], equipo.get(c)) for c in ('imei', 'color', 'pantalla')]
        for clave, etiqueta, tipo_input, _op in tipos.campos_extra(equipo['tipo']):
            if clave not in _EXTRAS_YA_EN_FILAS:
                valor = (equipo['extras'] or {}).get(clave)
                if tipo_input == 'si_no' and valor:
                    valor = 'Sí' if valor == 'si' else 'No'
                sueltos.append((etiqueta, valor))
        for etiqueta, valor in sueltos:
            texto = str(valor or '').strip()
            if texto and _norm(texto) not in valores and etiqueta not in salida:
                salida[etiqueta] = texto
    if equipo.get('tipo'):
        salida['Tipo de equipo'] = tipos.nombre(equipo['tipo'])
    for clave, etiqueta in TEXTOS_FICHA:
        valor = ficha.get(clave)
        if clave == 'estado':
            valor = ESTADOS_FICHA.get(valor, valor) if ficha else ''
        elif clave in ('recomendaciones', 'destacar'):
            valor = ' · '.join(str(x) for x in (valor or []))
        salida[etiqueta] = str(valor or '').strip()
    if not salida.get('Descripción'):
        salida['Descripción'] = str(estado.get('resumen') or '').strip()
    return salida


def diferencias(antes, despues):
    """[{etiqueta, antes, ahora}] de lo que cambió de un estado al otro."""
    a, d = contenido(antes or {}), contenido(despues or {})
    salida = []
    for etq in list(d) + [e for e in a if e not in d]:
        va, vd = a.get(etq, ''), d.get(etq, '')
        if _norm(va) != _norm(vd):
            salida.append({'etiqueta': etq, 'antes': va[:300], 'ahora': vd[:300]})
    return salida


def _plano(dic):
    return {k: _norm(v) for k, v in (dic or {}).items() if not _vacio(v)}


def igual(antes, despues):
    """¿Los dos estados dicen lo mismo? (la versión y la fecha de la ficha no cuentan)."""
    return (not diferencias(antes, despues)
            and (antes.get('ficha_codigo') or '') == (despues.get('ficha_codigo') or '')
            and _plano(antes.get('equipo')) == _plano(despues.get('equipo'))
            and _plano(antes.get('extras')) == _plano(despues.get('extras')))


def resumen_cambios(cambios, maximo=4):
    """«Memoria RAM: 8 GB → 16 GB; Procesador: … (y 3 más)»."""
    partes = []
    for c in cambios[:maximo]:
        antes = c['antes'] or 'sin dato'
        ahora = c['ahora'] or 'sin dato'
        partes.append(f"{c['etiqueta']}: {antes[:40]} → {ahora[:40]}")
    texto = '; '.join(partes)
    if len(cambios) > maximo:
        texto += f' (y {len(cambios) - maximo} más)'
    return texto


_LISTAS = set()


def _uno(fila):
    return fila[next(iter(fila.keys()))] if hasattr(fila, 'keys') else fila[0]


def _asegurar(cur):
    """La tabla de versiones, si la migración aún no llegó a esta base. Se crea en
    la MISMA transacción (otra conexión esperaría los bloqueos de esta)."""
    from database import _current_db_name
    db = _current_db_name()
    if db in _LISTAS:
        return
    cur.execute("SELECT to_regclass('public.st_fichas_versiones') AS t")
    if not _uno(cur.fetchone()):
        cur.execute(st.DDL_0024)
    _LISTAS.add(db)


def _existe_tabla():
    from database import get_db_cursor
    with get_db_cursor() as cur:
        cur.execute("SELECT to_regclass('public.st_fichas_versiones')")
        return bool(cur.fetchone()[0])


def _insertar(cur, equipo_id, estado, cambios, origen, importacion_id, usuario_id):
    cur.execute("""INSERT INTO st_fichas_versiones (equipo_id, version, estado, cambios, origen, importacion_id,
                                                    creado_por)
                   VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, %s, %s) RETURNING id""",
                (equipo_id, numero(estado), json.dumps(estado, ensure_ascii=False, default=str),
                 json.dumps(cambios, ensure_ascii=False, default=str), origen, importacion_id, usuario_id))
    fila = cur.fetchone()
    return fila['id'] if isinstance(fila, dict) or hasattr(fila, 'keys') else fila[0]


def _valor(fila, clave, i):
    return fila[clave] if isinstance(fila, dict) or hasattr(fila, 'keys') else fila[i]


def registrar(cur, equipo_id, antes, despues, origen, importacion_id=None, usuario_id=None):
    """Guarda la versión nueva del equipo (y, la primera vez, cómo estaba antes).
    Si la misma importación ya dejó una versión de este equipo, esa se pone al
    día en vez de crear otra. Devuelve el id de la versión o None si no cambió nada."""
    if igual(antes, despues):
        return None
    _asegurar(cur)
    cur.execute("""SELECT id, estado, importacion_id FROM st_fichas_versiones
                   WHERE equipo_id = %s AND activo ORDER BY id DESC LIMIT 2""", (equipo_id,))
    ultimas = cur.fetchall()
    if not ultimas and tiene_contenido(antes):          # la primera vez: cómo estaba antes, para no perderlo
        _insertar(cur, equipo_id, antes, [], 'anterior', None, usuario_id)
    elif importacion_id and ultimas and _valor(ultimas[0], 'importacion_id', 2) == importacion_id:
        propia = _valor(ultimas[0], 'id', 0)
        previa = _valor(ultimas[1], 'estado', 1) if len(ultimas) > 1 else antes
        cur.execute("""UPDATE st_fichas_versiones SET estado = %s::jsonb, cambios = %s::jsonb, version = %s
                       WHERE id = %s""",
                    (json.dumps(despues, ensure_ascii=False, default=str),
                     json.dumps(diferencias(previa, despues), ensure_ascii=False, default=str),
                     numero(despues), propia))
        return propia
    return _insertar(cur, equipo_id, despues, diferencias(antes, despues), origen, importacion_id, usuario_id)


def de_equipo(equipo_id):
    """Versiones activas del equipo, la más nueva primero (para su página)."""
    from database import get_db_cursor
    if not _existe_tabla():
        return []
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT v.id, v.version, v.cambios, v.origen, v.importacion_id, v.creado_en,
                              u.nombre AS usuario_nombre,
                              (SELECT a->>'nombre' FROM st_importaciones i, jsonb_array_elements(i.archivos) a
                               WHERE i.id = v.importacion_id LIMIT 1) AS archivo
                       FROM st_fichas_versiones v LEFT JOIN usuarios u ON u.id = v.creado_por
                       WHERE v.equipo_id = %s AND v.activo ORDER BY v.id DESC""", (equipo_id,))
        filas = [dict(r) for r in cur.fetchall()]
    for i, f in enumerate(filas):
        f['actual'] = i == 0
        f['origen_nombre'] = ORIGENES.get(f['origen'], f['origen'])
    return filas


def obtener(equipo_id, version_id):
    from database import get_db_cursor
    if not _existe_tabla():
        return None
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT id, version, estado, creado_en FROM st_fichas_versiones
                       WHERE id = %s AND equipo_id = %s AND activo""", (version_id, equipo_id))
        fila = cur.fetchone()
    return dict(fila) if fila else None


def deshacer_importacion(cur, lote_id, aplicadas):
    """Deshace lo que una importación cambió en equipos que ya existían: cada dato
    vuelve a como estaba si nadie lo cambió después; su versión queda inactiva.
    `aplicadas`: [{equipo_id, antes, despues}] del resultado. Devuelve cuántos datos volvieron."""
    _asegurar(cur)
    devueltos = 0
    for ap in aplicadas or []:
        eid, antes, despues = ap['equipo_id'], ap.get('antes') or {}, ap.get('despues') or {}
        cur.execute('SELECT * FROM st_equipos WHERE id = %s FOR UPDATE', (eid,))
        fila = cur.fetchone()
        if not fila:
            continue
        actual = estado_de(dict(fila))
        sets, params = [], []
        for c in CAMPOS:
            va, vd, vh = (antes.get('equipo') or {}).get(c), (despues.get('equipo') or {}).get(c), actual['equipo'].get(c)
            if va != vd and vh == vd:
                sets.append(f'{c} = %s')
                params.append(va)
        if (antes.get('extras') or {}) != (despues.get('extras') or {}) and actual['extras'] == (despues.get('extras') or {}):
            sets.append('extras = %s::jsonb')
            params.append(json.dumps(antes.get('extras') or {}, ensure_ascii=False))
        if antes.get('resumen') != despues.get('resumen') and actual['resumen'] == despues.get('resumen'):
            sets.append('resumen_ia = %s')
            params.append(antes.get('resumen'))
        if (antes.get('ficha') or {}) != (despues.get('ficha') or {}) and actual['ficha'] == (despues.get('ficha') or {}):
            sets.append('ficha = %s::jsonb')
            params.append(json.dumps(antes.get('ficha') or {}, ensure_ascii=False))
        if antes.get('ficha_codigo') != despues.get('ficha_codigo') and actual['ficha_codigo'] == despues.get('ficha_codigo'):
            sets.append('ficha_codigo = %s')
            params.append(antes.get('ficha_codigo'))
        if ap.get('notas') and fila['notas'] == ap['notas']['despues']:
            sets.append('notas = %s')
            params.append(ap['notas']['antes'])
        if sets:
            cur.execute(f"UPDATE st_equipos SET {', '.join(sets)}, actualizado_en = NOW() WHERE id = %s",
                        (*params, eid))
            devueltos += len(sets)
    cur.execute('UPDATE st_fichas_versiones SET activo = FALSE WHERE importacion_id = %s AND activo', (lote_id,))
    return devueltos
