"""Documentos internos del negocio para el asistente del panel.

Solo lectura y nunca pública: busca en lo que el dueño escribió en
/admin/ia/documentos, filtrado por el rol de quien pregunta
(services/ia_rag/internos.py).
"""

from services.ia_datos.acceso import contexto_actual

_MAX_TEXTO_PARTE = 1500


def documentos_internos(texto=None):
    """Lo que dicen los procedimientos, políticas y manuales sobre `texto`."""
    from services.ia_rag.internos import buscar_para_rol
    buscado = (texto or '').strip()
    if len(buscado) < 3:
        return {'conclusion': 'Dime qué procedimiento, política o manual buscas '
                              '(por ejemplo: «procedimiento de apertura»).'}
    docs = buscar_para_rol(buscado, contexto_actual().rol_id, limite=3)
    if not docs:
        return {'buscado': buscado, 'encontrados': 0,
                'conclusion': f'No encontré documentos internos sobre «{buscado}». El dueño '
                              'puede agregarlos en Asistente IA → Documentos internos.'}
    return {'buscado': buscado, 'encontrados': len(docs),
            'documentos': [{'titulo': d['titulo'], 'texto': d['texto'][:_MAX_TEXTO_PARTE]}
                           for d in docs]}
