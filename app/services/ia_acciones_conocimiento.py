"""Acciones del panel sobre la base de conocimiento: preguntas frecuentes por
chat («Agrega a las preguntas frecuentes: ¿Abren los domingos? Sí, de 9 a 2»).

Como reseñas y tickets (services/ia_acciones_atencion.py), el motor
(services/ia_acciones.py) autoriza, guarda la propuesta, la muestra y solo
escribe cuando la persona confirma. Diferencias:

  - No usa el modelo de IA: la pregunta y la respuesta se toman LITERALES de lo
    que escribió la persona (entre comillas, «pregunta: … respuesta: …» o
    «¿…? respuesta»). Es texto público del chat del sitio: la IA no lo redacta.
    Por eso funciona aunque el motor local esté apagado.
  - Cada cambio queda en la bitácora de la base de conocimiento
    (ia_conocimiento_log) EN LA MISMA transacción, con origen «asistente», y se
    puede deshacer desde /admin/chat-publico/conocimiento.
  - Nada se borra: «elimina/quita la pregunta frecuente…» la despublica
    (el chat deja de usarla) y se puede volver a publicar.
"""
import re

from services.ia.texto import normalizar
from services.ia_acciones import AccionAclarar, AccionError, _aparece, _entero, _texto
from services.ia_acciones_atencion import _corto, _elegir, _hay_tabla
from services.ia_acciones_crm import _sin_cambios, _snapshot

MAX_PREGUNTA = 200
MAX_RESPUESTA = 1500
_CAMPOS = ('title', 'subtitle', 'description', 'extra_text', 'sort_order', 'is_active',
           'image_url', 'cta_label', 'cta_url')
_RELLENO = ('pregunta', 'frecuente', 'faq', 'respuesta', 'sobre', 'dice', 'habla', 'tema')

# ── Detección (frase ya normalizada: minúsculas y sin tildes) ──────────────
_OBJ = r'(?:preguntas?\s+frecuentes?|faqs?)\b'
_CORTESIA = (r'^(?:(?:por favor|porfa|porfavor|puedes|podrias|ayudame a|quiero|necesito|'
             r'hay que)\s+)*')
_MEDIO = r'\b(?P<medio>[^.?!:]{0,60}?)'
_VERBOS = {
    'crear_faq': r'(?:agrega|agregar|agregale|agregame|anade|anadir|anadele|crea|crear|creame|'
                 r'registra|registrar|guarda|guardar|incluye|incluir|mete|meter|suma|sumale)',
    'editar_faq': r'(?:cambia|cambiar|cambiale|edita|editar|modifica|modificar|actualiza|'
                  r'actualizar|corrige|corregir)',
    'archivar_faq': r'(?:quita|quitar|quitale|elimina|eliminar|borra|borrar|oculta|ocultar|'
                    r'despublica|despublicar|archiva|archivar|desactiva|desactivar|saca|sacar)',
    'publicar_faq': r'(?:publica|publicar|activa|activar|reactiva|reactivar|vuelve a publicar)',
}
_ORDENES = {tipo: re.compile(_CORTESIA + verbo + _MEDIO + _OBJ) for tipo, verbo in _VERBOS.items()}
# «Crea una tarea para revisar las preguntas frecuentes» es una tarea.
_OTRO_OBJETO = re.compile(r'\b(?:tareas?|recordatorios?|oportunidad(?:es)?|actividad(?:es)?|'
                          r'llamadas?|productos?|contactos?|clientes?|proveedor(?:es)?|'
                          r'resenas?|tickets?|categorias?)\b')

TIPOS = tuple(_ORDENES)


def orden_de_conocimiento(frase):
    """El proceso de la base de conocimiento de una frase normalizada, o None."""
    frase = frase.lstrip('¿¡ \t')
    for tipo, patron in _ORDENES.items():
        hallado = patron.search(frase)
        if hallado and not _OTRO_OBJETO.search(hallado.group('medio')):
            return tipo
    return None


# ── Lectura literal de la orden ─────────────────────────────────────────────
_OBJ_TEXTO = re.compile(r'\b(?:preguntas?\s+frecuentes?|faqs?)\b', re.I)
_CITA = re.compile(r'[«"“]([^»"”]{2,1500})[»"”]')
_ETIQUETADA = re.compile(r'pregunta\s*:\s*(?P<p>.+?)\s*(?:,|;|\.|\n)?\s*'
                         r'(?:respuesta|responde|contesta)\s*:\s*(?P<r>.+)$', re.I | re.S)
_ARRANQUE = re.compile(r'^\s*(?::|,|;|-|—|que diga|diciendo|con el texto|con la pregunta)\s*', re.I)
_ID_DICHO = re.compile(r'dato adicional:\s*id\s*(\d{1,9})\b', re.I)


def _partes(pregunta):
    """(orden, [datos adicionales]) — combinar() agrega «. Dato adicional: …»."""
    trozos = str(pregunta or '').split('. Dato adicional:')
    return trozos[0], [t.strip() for t in trozos[1:] if t.strip()]


def pregunta_y_respuesta(texto):
    """(pregunta, respuesta) tal como se escribieron, o (None, None)."""
    texto = (texto or '').strip()
    if not texto:
        return None, None
    etiquetada = _ETIQUETADA.search(texto)
    if etiquetada:
        return etiquetada.group('p').strip(' "«»“”'), etiquetada.group('r').strip(' "«»“”')
    citas = [c.strip() for c in _CITA.findall(texto)]
    if len(citas) >= 2:
        return citas[0], citas[1]
    cierre = texto.find('?')
    if cierre > 0:
        pregunta = texto[:cierre + 1].strip()
        respuesta = re.sub(r'^[\s,;:.\-—]*(?:r/|respuesta:)?\s*', '', texto[cierre + 1:], flags=re.I)
        return pregunta, (respuesta.strip() or None)
    return None, None


def _tras_objeto(orden):
    """Lo que sigue a «pregunta(s) frecuente(s)» en la orden."""
    hallado = _OBJ_TEXTO.search(orden)
    return orden[hallado.end():] if hallado else ''


def _antes_del_objeto(orden):
    hallado = _OBJ_TEXTO.search(orden)
    return orden[:hallado.start()] if hallado else ''


def _referencia(orden):
    """Cuál pregunta frecuente: lo que sigue al objeto hasta «:» o comillas
    («la pregunta frecuente de domicilios: …» → «de domicilios»), o lo que va
    entre el verbo y el objeto («cambia la de domicilios en las preguntas…»)."""
    despues = re.split(r'[:«"“]', _tras_objeto(orden), maxsplit=1)[0].strip(' .,;')
    if despues and not despues.startswith('?'):
        return despues[:120]
    antes = re.sub(r'^\W*\w+\s*', '', _antes_del_objeto(orden)).strip(' .,;')
    return antes[:120]


def _nuevo_texto(orden):
    """El texto nuevo de una edición: entre comillas o tras el primer «:»."""
    citas = [c.strip() for c in _CITA.findall(orden)]
    if citas:
        return ' '.join(citas) if len(citas) > 1 and '?' in citas[0] else citas[0], citas
    if ':' in orden:
        return orden.split(':', 1)[1].strip(), []
    return '', []


def plan(pregunta, tipo):
    """El plan de la acción, armado solo con lo que escribió la persona."""
    orden, adicionales = _partes(pregunta)
    elegido = _ID_DICHO.search(str(pregunta or ''))
    textos = [a for a in adicionales if not re.fullmatch(r'ID \d{1,9}', a)]

    if tipo == 'crear_faq':
        cuerpo = _ARRANQUE.sub('', _tras_objeto(orden), count=1)
        p, r = pregunta_y_respuesta(cuerpo)
        for dato in textos:                       # respuestas a «¿Cuál es…?»
            if not p:
                p, r = pregunta_y_respuesta(dato)
                if not p and dato.rstrip().endswith('?'):
                    p = dato.strip()
            elif not r:
                r = dato.strip()
        if not p:
            raise AccionAclarar('¿Cuál es la pregunta y su respuesta? Escríbelas así: '
                                '«¿Abren los domingos? Sí, de 9 a 2».')
        if not r:
            raise AccionAclarar(f'¿Qué respuesta debe dar el chat a «{_corto(p, 80)}»? '
                                'Escríbela tal cual.')
        return {'tipo': tipo, 'pregunta': p, 'respuesta': r}

    plan_ = {'tipo': tipo}
    numero = re.fullmatch(r'\s*(?:la\s+|el\s+)?(?:id\s*|#\s*|n(?:umero|ro)?\.?\s*)?(\d{1,9})\s*',
                          _referencia(orden), re.I)
    if elegido:
        plan_['faq_id'] = int(elegido.group(1))
    elif numero:
        plan_['faq_id'] = int(numero.group(1))
    else:
        plan_['faq'] = _referencia(orden)
    if tipo != 'editar_faq':
        return plan_
    nuevo, _citas = _nuevo_texto(orden)
    nuevo = nuevo or next(iter(textos), '')
    if not nuevo:
        raise AccionAclarar('¿Cuál es la nueva respuesta? Escríbela tal cual la debe dar el chat.')
    p, r = pregunta_y_respuesta(nuevo)
    if p and r:
        plan_['pregunta'], plan_['respuesta'] = p, r
    elif p and nuevo.strip() == p:
        plan_['pregunta'] = p                      # solo cambia cómo está escrita la pregunta
    else:
        plan_['respuesta'] = nuevo.strip()
    return plan_


def datos_dichos(plan_, fuentes, fuente):
    """Cada texto debe estar en lo que escribió la persona (nunca de la IA)."""
    for campo in ('pregunta', 'respuesta', 'faq'):
        valor = plan_.get(campo)
        if valor and not _aparece(valor, fuente):
            raise AccionAclarar('No identifiqué el texto exacto. Escríbelo así: '
                                '«¿Abren los domingos? Sí, de 9 a 2».')
    if plan_.get('faq_id') is not None and not re.search(rf'\b{int(plan_["faq_id"])}\b', fuente):
        raise AccionAclarar('¿Cuál pregunta frecuente? Dime de qué trata o su ID.')


# ── Registro ────────────────────────────────────────────────────────────────
_SQL = ("SELECT id, title, COALESCE(description, '') AS description, is_active "
        "FROM public_site_items WHERE item_type = 'faq'")


def _etiqueta(f):
    return f"«{_corto(f['title'], 70)}»" + ('' if f['is_active'] else ' (no publicada)')


def faq(cur, plan_, filtro='TRUE', bloquear=False):
    if not _hay_tabla(cur, 'public_site_items'):
        raise AccionError('Esta tienda todavía no tiene preguntas frecuentes.')
    if plan_.get('faq_id') is not None:
        fid = _entero(plan_['faq_id'], 'el ID de la pregunta frecuente')
        cur.execute(_SQL + ' AND id = %s' + (' FOR UPDATE' if bloquear else ''), (fid,))
        fila = cur.fetchone()
        if not fila:
            raise AccionAclarar(f'No encontré la pregunta frecuente con el ID {fid}. ¿De qué trata?')
        return dict(fila)
    referencia = _texto(plan_.get('faq'), 'pregunta frecuente', 200) or ''
    estado = {'is_active': 'publicada', 'NOT is_active': 'no publicada'}.get(filtro, '')
    que = 'una pregunta frecuente' + (f' {estado}' if estado else '') + (
        f' sobre «{referencia}»' if referencia else '')
    return _elegir(cur, f'({_SQL}) f', "translate(lower(title || ' ' || description), %s, %s)",
                   filtro, referencia, _RELLENO, que, _etiqueta)


def _foto(cur, faq_id):
    cur.execute(f"SELECT id, {', '.join(_CAMPOS)} FROM public_site_items WHERE id = %s", (faq_id,))
    fila = cur.fetchone()
    return dict(fila) if fila else None


def _textos(plan_):
    p = _texto(plan_.get('pregunta'), 'pregunta', MAX_PREGUNTA) if plan_.get('pregunta') else None
    r = _texto(plan_.get('respuesta'), 'respuesta', MAX_RESPUESTA) if plan_.get('respuesta') else None
    return p, r


def _duplicada(cur, pregunta, excluir=None):
    cur.execute(_SQL + (' AND id <> %s' if excluir else ''), ((excluir,) if excluir else ()))
    clave = ' '.join(re.sub(r'[^a-z0-9 ]+', ' ', normalizar(pregunta)).split())
    for f in cur.fetchall():
        if ' '.join(re.sub(r'[^a-z0-9 ]+', ' ', normalizar(f['title'])).split()) == clave:
            return dict(f)
    return None


_DESHACER = 'Queda en el historial de la base de conocimiento y se puede deshacer.'


def _preparar_crear(cur, plan_):
    pregunta, respuesta = _textos(plan_)
    if not pregunta or not respuesta:
        raise AccionAclarar('¿Cuál es la pregunta y su respuesta?')
    if not _hay_tabla(cur, 'public_site_items'):
        from services.public_site_service import bootstrap_public_site_structure
        bootstrap_public_site_structure()
    igual = _duplicada(cur, pregunta)
    if igual:
        raise AccionError(f"Ya existe esa pregunta frecuente (ID {igual['id']}). Para cambiar su "
                          f"respuesta: «Cambia la pregunta frecuente {igual['id']}: …».")
    payload = {'tipo': 'crear_faq', 'pregunta': pregunta, 'respuesta': respuesta}
    detalles = [f'Pregunta: «{pregunta}»', f'Respuesta: «{respuesta}»',
                'Quedará publicada: el chat del sitio la usa desde ese momento.', _DESHACER]
    return payload, f'Agregar a las preguntas frecuentes: «{_corto(pregunta, 80)}».', detalles


def _preparar_editar(cur, plan_):
    pregunta, respuesta = _textos(plan_)
    actual = faq(cur, plan_)
    cambios = {}
    if pregunta and pregunta != actual['title']:
        if _duplicada(cur, pregunta, excluir=actual['id']):
            raise AccionError('Ya hay otra pregunta frecuente escrita igual.')
        cambios['title'] = pregunta
    if respuesta and respuesta != actual['description']:
        cambios['description'] = respuesta
    if not cambios:
        raise AccionError('Esa pregunta frecuente ya dice eso; no hay cambios.')
    payload = {'tipo': 'editar_faq', 'faq_id': actual['id'], 'cambios': cambios,
               'snapshot': _snapshot(actual, ('title', 'description', 'is_active'))}
    detalles = [f"Pregunta frecuente ID {actual['id']}: «{_corto(actual['title'], 120)}»"]
    if 'title' in cambios:
        detalles.append(f"Pregunta: «{_corto(actual['title'], 120)}» → «{cambios['title']}»")
    if 'description' in cambios:
        detalles += [f"Respuesta actual: «{_corto(actual['description'], 300)}»",
                     f"Respuesta nueva: «{cambios['description']}»"]
    detalles.append(_DESHACER)
    return payload, f"Cambiar la pregunta frecuente «{_corto(actual['title'], 70)}».", detalles


def _preparar_estado(cur, plan_):
    publicar = plan_['tipo'] == 'publicar_faq'
    actual = faq(cur, plan_, filtro='NOT is_active' if publicar else 'is_active')
    if bool(actual['is_active']) == publicar:
        raise AccionError(f"La pregunta frecuente {_etiqueta(actual)} ya está "
                          f"{'publicada' if publicar else 'sin publicar'}.")
    payload = {'tipo': plan_['tipo'], 'faq_id': actual['id'],
               'snapshot': _snapshot(actual, ('title', 'description', 'is_active'))}
    detalles = [f"Pregunta frecuente ID {actual['id']}: «{_corto(actual['title'], 120)}»",
                f"Respuesta: «{_corto(actual['description'], 200)}»"]
    if publicar:
        detalles.append('El chat del sitio vuelve a usarla.')
    else:
        detalles.append('El chat del sitio deja de usarla. No se borra: la puedes volver a publicar.')
    detalles.append(_DESHACER)
    verbo = 'Publicar' if publicar else 'Despublicar'
    return payload, f"{verbo} la pregunta frecuente «{_corto(actual['title'], 70)}».", detalles


# ── Escritura al confirmar ──────────────────────────────────────────────────

def _al_dia(cur, faq_id):
    """El índice del chat y la caché del sitio, en la misma transacción."""
    from services.ia_rag.indexador import _items_del_sitio, _sql_tsv, indice_disponible
    if indice_disponible(cur):
        cur.execute("DELETE FROM ia_documentos WHERE fuente = 'faq' AND fuente_id = %s",
                    (str(faq_id),))
        _items_del_sitio(cur, _sql_tsv(cur), item_type='faq', fuente_id=faq_id)
    try:
        from services.public_site_service import clear_public_site_cache
        clear_public_site_cache()
    except Exception:  # noqa: BLE001
        pass


def _ejecutar_crear(cur, p, usuario):
    from services.ia_rag import bitacora
    pregunta, respuesta = _textos(p)
    if _duplicada(cur, pregunta):
        raise AccionError('Esa pregunta frecuente ya existe. No se hizo ningún cambio.')
    cur.execute("""INSERT INTO public_site_items
                       (item_type, title, subtitle, description, image_url, cta_label, cta_url,
                        extra_text, sort_order, is_active, created_at, updated_at)
                   VALUES ('faq', %s, '', %s, '', '', '', '', 10, TRUE,
                           CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) RETURNING id""",
                (pregunta, respuesta))
    fid = cur.fetchone()['id']
    bitacora.registrar_en(cur, 'faq', 'crear', fid, pregunta, None, _foto(cur, fid),
                          usuario_id=usuario)
    _al_dia(cur, fid)
    return {'mensaje': f'Pregunta frecuente agregada: «{_corto(pregunta, 80)}». '
                       'El chat del sitio ya la usa.', 'faq_id': fid}


def _ejecutar_editar(cur, p, usuario):
    from services.ia_rag import bitacora
    actual = faq(cur, {'faq_id': p['faq_id']}, bloquear=True)
    _sin_cambios(actual, p.get('snapshot'), 'La pregunta frecuente')
    cambios = {k: v for k, v in (p.get('cambios') or {}).items() if k in ('title', 'description')}
    if not cambios:
        raise AccionError('La propuesta no trae cambios. Prepara una nueva.')
    antes = _foto(cur, actual['id'])
    asignaciones = ', '.join(f'{k} = %s' for k in cambios)
    cur.execute(f'UPDATE public_site_items SET {asignaciones}, updated_at = CURRENT_TIMESTAMP '
                "WHERE id = %s AND item_type = 'faq'", (*cambios.values(), actual['id']))
    despues = _foto(cur, actual['id'])
    bitacora.registrar_en(cur, 'faq', 'editar', actual['id'], despues['title'], antes, despues,
                          usuario_id=usuario)
    _al_dia(cur, actual['id'])
    return {'mensaje': f"Pregunta frecuente «{_corto(despues['title'], 70)}» actualizada.",
            'faq_id': actual['id']}


def _ejecutar_estado(cur, p, usuario):
    from services.ia_rag import bitacora
    publicar = p['tipo'] == 'publicar_faq'
    actual = faq(cur, {'faq_id': p['faq_id']}, bloquear=True)
    _sin_cambios(actual, p.get('snapshot'), 'La pregunta frecuente')
    antes = _foto(cur, actual['id'])
    cur.execute("UPDATE public_site_items SET is_active = %s, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = %s AND item_type = 'faq'", (publicar, actual['id']))
    despues = _foto(cur, actual['id'])
    bitacora.registrar_en(cur, 'faq', 'publicar' if publicar else 'despublicar', actual['id'],
                          actual['title'], antes, despues, usuario_id=usuario)
    _al_dia(cur, actual['id'])
    estado = 'publicada: el chat del sitio vuelve a usarla' if publicar else \
        'despublicada: el chat del sitio ya no la usa'
    return {'mensaje': f"Pregunta frecuente «{_corto(actual['title'], 70)}» {estado}.",
            'faq_id': actual['id']}


_PREPARAR = {'crear_faq': _preparar_crear, 'editar_faq': _preparar_editar,
             'archivar_faq': _preparar_estado, 'publicar_faq': _preparar_estado}
_EJECUTAR = {'crear_faq': _ejecutar_crear, 'editar_faq': _ejecutar_editar,
             'archivar_faq': _ejecutar_estado, 'publicar_faq': _ejecutar_estado}


def preparar(cur, plan_):
    return _PREPARAR[plan_['tipo']](cur, plan_)


def ejecutar(cur, fila, usuario):
    return _EJECUTAR[fila['tipo']](cur, fila['payload'], usuario)
