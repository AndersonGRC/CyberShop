"""Contactos del CRM para el asistente del panel: buscarlos y ver su ID.

A diferencia de comercial.py (solo agregados, sin teléfono ni correo), esta
consulta SÍ devuelve los datos del contacto: es el mismo directorio que la
persona ya ve en el CRM, y la usa para saber a qué contacto se refiere antes
de editarlo. Por eso:
  - exige el permiso `crm` (el mismo del módulo CRM), y
  - es solo local (extra nube=False): estos datos personales nunca se
    redactan con el respaldo en la nube.
"""
from database import get_db_cursor

from services.ia_datos.base import _existe

LIMITE = 10


def tareas_pendientes(limite=15, **_):
    """Tareas pendientes del CRM con su ID, contacto, prioridad y vencimiento,
    para completarlas o cambiarlas por su ID. Primero las vencidas."""
    try:
        limite = max(1, min(int(limite or 15), 40))
    except (TypeError, ValueError):
        limite = 15
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'crm_tareas'):
            return {'conclusion': 'Este negocio todavía no usa tareas en el CRM.'}
        cur.execute("""SELECT t.id, t.titulo, t.prioridad, t.fecha_limite, c.nombre AS contacto,
                              (t.fecha_limite < CURRENT_DATE) AS vencida
                       FROM crm_tareas t JOIN crm_contactos c ON c.id = t.contacto_id
                       WHERE t.estado = 'pendiente'
                       ORDER BY (t.fecha_limite IS NULL), t.fecha_limite,
                                CASE t.prioridad WHEN 'alta' THEN 0 WHEN 'media' THEN 1 ELSE 2 END, t.id
                       LIMIT %s""", (limite,))
        filas = cur.fetchall()
        cur.execute("SELECT COUNT(*) AS n FROM crm_tareas WHERE estado = 'pendiente'")
        total = int(cur.fetchone()['n'])
    if not filas:
        return {'tareas_pendientes': 0, 'conclusion': 'No hay tareas pendientes en el CRM.'}
    return {'tareas_pendientes': total,
            'tareas': [{'id': f['id'], 'tarea': f['titulo'], 'contacto': f['contacto'],
                        'prioridad': f['prioridad'],
                        'vence': str(f['fecha_limite']) if f['fecha_limite'] else None,
                        'vencida': bool(f['vencida'])} for f in filas]}


def buscar_contactos(texto='', limite=LIMITE, **_):
    """Contactos activos que coinciden con lo dicho (nombre, empresa, correo o
    teléfono). Sin texto: los más recientes."""
    from services.ia.buscador import contactos
    try:
        limite = max(1, min(int(limite or LIMITE), 20))
    except (TypeError, ValueError):
        limite = LIMITE
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'crm_contactos'):
            return {'conclusion': 'Este negocio todavía no tiene contactos en el CRM.'}
        referencia = str(texto or '').strip()
        if referencia:
            filas, modo = contactos(cur, referencia, activos=True, limite=limite)
        else:
            cur.execute("""SELECT id, nombre, tipo, empresa, email, telefono, whatsapp, ciudad
                           FROM crm_contactos WHERE activo = TRUE
                           ORDER BY id DESC LIMIT %s""", (limite,))
            filas, modo = [dict(f) for f in cur.fetchall()], 'recientes'
        cur.execute('SELECT COUNT(*) AS n FROM crm_contactos WHERE activo = TRUE')
        total = int(cur.fetchone()['n'])

    campos = ('id', 'nombre', 'tipo', 'empresa', 'email', 'telefono', 'whatsapp', 'ciudad')
    salida = {'buscado': referencia or None, 'contactos_activos': total,
              'contactos': [{k: f.get(k) for k in campos if f.get(k) not in (None, '')}
                            for f in filas[:limite]]}
    if not filas:
        salida['conclusion'] = (f'No encontré contactos activos como «{referencia}».'
                                if referencia else 'No hay contactos activos en el CRM.')
    elif modo == 'parcial':
        salida['nota'] = ('Ninguno coincide con todas las palabras buscadas; '
                          'estos son los más parecidos.')
    return salida
