"""Operaciones rápidas sobre lo que sabe la IA, todas con bitácora.

Las pantallas (preguntas frecuentes, documentos internos y la base de
conocimiento) pasan por aquí en vez de escribir directo: así cada alta,
edición, borrado o archivo queda en services/ia_rag/bitacora.py con su foto de
antes y después, y se puede deshacer con restaurar().

Las preguntas frecuentes siguen guardándose con las funciones genéricas de
services/public_site_service.py (item_type='faq'); aquí solo se envuelven.
"""

from database import get_db_cursor
from services.ia_rag import bitacora

_CAMPOS_FAQ = ('title', 'subtitle', 'description', 'extra_text', 'sort_order', 'is_active',
               'image_url', 'cta_label', 'cta_url')
RESTAURABLES = {('faq', 'eliminar'), ('faq', 'editar'),
                ('documento', 'editar'), ('documento', 'archivar')}


def puede_restaurar(fila):
    return (fila.get('tipo'), fila.get('accion')) in RESTAURABLES and bool(fila.get('antes'))


# ── Preguntas frecuentes ────────────────────────────────────────

def faq_obtener(item_id):
    if not item_id:
        return None
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT to_regclass('public.public_site_items') AS t")
            if cur.fetchone()['t'] is None:
                return None
            cur.execute(f"""SELECT id, {', '.join(_CAMPOS_FAQ)} FROM public_site_items
                            WHERE id = %s AND item_type = 'faq'""", (item_id,))
            fila = cur.fetchone()
            return dict(fila) if fila else None
    except Exception:  # noqa: BLE001
        return None


def _faq_recien_creada(titulo):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT id FROM public_site_items WHERE item_type = 'faq' AND title = %s
                       ORDER BY id DESC LIMIT 1""", (titulo,))
        fila = cur.fetchone()
        return fila['id'] if fila else None


def faq_guardar(datos, item_id=None, archivo=None, root_path=None, origen='panel',
                pregunta=None, accion=None):
    """Crea o edita una pregunta frecuente y deja la bitácora. Devuelve su id.

    `pregunta`: texto de una pregunta que el chat no supo responder y que esta
    FAQ responde; queda marcada como atendida.
    """
    from services.public_site_service import save_public_site_item
    titulo = (datos.get('title') or '').strip()
    if not titulo:
        raise ValueError('Escribe la pregunta.')
    if not (datos.get('description') or '').strip():
        raise ValueError('Escribe la respuesta.')
    antes = faq_obtener(item_id) if item_id else None
    if item_id and not antes:
        raise ValueError('Esa pregunta frecuente ya no existe.')
    form = {k: datos.get(k) for k in ('title', 'subtitle', 'description', 'extra_text',
                                      'sort_order', 'is_active', 'cta_label', 'cta_url',
                                      'current_image_url') if datos.get(k) is not None}
    form['item_type'] = 'faq'
    if item_id:
        form['item_id'] = str(item_id)
    save_public_site_item(form, archivo, root_path)
    if not item_id:
        item_id = _faq_recien_creada(titulo)
    despues = faq_obtener(item_id)
    bitacora.registrar('faq', accion or ('editar' if antes else 'crear'), item_id,
                       (despues or {}).get('title') or titulo, antes, despues, origen)
    if pregunta:
        bitacora.registrar('pregunta', 'responder', bitacora.clave_pregunta(pregunta), pregunta,
                           despues={'faq_id': item_id, 'faq': titulo}, origen=origen)
    return item_id


def faq_eliminar(item_id, origen='panel'):
    """Borra la pregunta frecuente, pero su foto queda en la bitácora y se
    puede restaurar desde el historial."""
    from services.public_site_service import delete_public_site_item
    antes = faq_obtener(item_id)
    if not antes:
        return False
    delete_public_site_item(item_id, item_type='faq')
    bitacora.registrar('faq', 'eliminar', item_id, antes['title'], antes, None, origen)
    return True


def faq_cambiar_estado(item_id, origen='panel'):
    from services.public_site_service import toggle_public_site_item
    antes = faq_obtener(item_id)
    if not antes:
        return False
    toggle_public_site_item(item_id, item_type='faq')
    despues = faq_obtener(item_id)
    accion = 'publicar' if (despues or {}).get('is_active') else 'despublicar'
    bitacora.registrar('faq', accion, item_id, antes['title'], antes, despues, origen)
    return True


# ── Restaurar desde el historial ────────────────────────────────

def restaurar(log_id):
    """Deshace un cambio de la bitácora. Devuelve (ok, mensaje, tipo, objeto_id)."""
    fila = bitacora.obtener(log_id)
    if not fila or not puede_restaurar(fila):
        return False, 'Ese cambio no se puede deshacer.', None, None
    antes = fila['antes']
    if fila['tipo'] == 'faq':
        actual = faq_obtener(fila['objeto_id'])
        datos = {k: antes.get(k) for k in _CAMPOS_FAQ if k != 'image_url'}
        datos['current_image_url'] = antes.get('image_url') or ''
        datos['is_active'] = 'on' if antes.get('is_active') else None
        datos['sort_order'] = str(antes.get('sort_order') or '')
        if actual:
            faq_guardar(datos, item_id=actual['id'], origen='historial', accion='restaurar')
            return True, 'Pregunta frecuente devuelta a como estaba.', 'faq', actual['id']
        nuevo = faq_guardar(datos, origen='historial', accion='restaurar')
        return True, 'Pregunta frecuente restaurada.', 'faq', nuevo

    from services.ia_rag import internos
    doc = internos.obtener(int(fila['objeto_id']))
    if not doc:
        return False, 'Ese documento ya no existe.', None, None
    if fila['accion'] == 'archivar':
        internos.cambiar_estado(doc['id'], True, origen='historial')
        return True, 'Documento restaurado: el asistente vuelve a consultarlo.', 'documento', doc['id']
    internos.guardar(antes.get('titulo'), antes.get('texto'), antes.get('visibilidad'),
                     doc_id=doc['id'], origen='historial', accion='restaurar')
    return True, 'Documento devuelto a la versión anterior.', 'documento', doc['id']


# ── Preguntas que el chat no supo responder ─────────────────────

def preguntas_pendientes(limite=30):
    """Las preguntas sin respuesta, agrupadas: la misma pregunta escrita de
    varias formas cuenta una vez, con cuántas veces se hizo. Las ya
    respondidas con una FAQ o descartadas no aparecen."""
    from services.chat_publico.historial import preguntas_sin_responder
    atendidas = bitacora.preguntas_atendidas()
    grupos = {}
    for p in preguntas_sin_responder(limite=100):          # de la más nueva a la más vieja
        clave = bitacora.clave_pregunta(p['pregunta'])
        if not bitacora.normalizar_pregunta(p['pregunta']) or clave in atendidas:
            continue
        g = grupos.setdefault(clave, {'clave': clave, 'pregunta': p['pregunta'],
                                      'veces': 0, 'ultima': p['fecha']})
        g['veces'] += 1
    orden = sorted(grupos.values(), key=lambda g: g['ultima'], reverse=True)
    orden.sort(key=lambda g: g['veces'], reverse=True)       # estable: más pedidas primero
    return orden[:max(1, int(limite or 30))]


def descartar_pregunta(pregunta, origen='panel'):
    texto = (pregunta or '').strip()
    if not texto:
        return False
    return bitacora.registrar('pregunta', 'descartar', bitacora.clave_pregunta(texto), texto,
                              origen=origen)


# ── Probar una pregunta ─────────────────────────────────────────

def probar(pregunta, rol_id=None, con_internos=False):
    """Qué textos encontraría la IA para esa pregunta. Solo lectura: no se
    registra como consulta ni pasa por el modelo."""
    from services.ia_rag.buscar import buscar
    from services.ia_rag.indexador import mantener_al_dia
    texto = (pregunta or '').strip()[:300]
    if len(texto) < 3:
        return {'publico': [], 'internos': []}
    mantener_al_dia()
    resultado = {'publico': buscar(texto, solo_publico=True, limite=5), 'internos': []}
    if con_internos:
        from services.ia_rag.internos import buscar_para_rol
        resultado['internos'] = buscar_para_rol(texto, rol_id, limite=3)
    return resultado
