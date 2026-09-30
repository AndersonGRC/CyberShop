"""Acciones del panel sobre la atención al cliente: reseñas y tickets de
soporte (fase 4 del CRUD de la IA).

Como en el catálogo y el CRM, el motor (services/ia_acciones.py) interpreta,
autoriza, guarda la propuesta y confirma; aquí solo están la vista previa
(preparar) y la escritura al confirmar (ejecutar). Reglas replicadas del panel:
  - Reseña (routes/admin.py, /admin/resenas): aprobar = aprobado TRUE (queda
    visible en la página del producto); responder = respuesta (máx. 1.500) +
    respuesta_fecha. Se publica el texto TAL CUAL lo escribió la persona: la IA
    no redacta respuestas públicas. Desde la IA no se rechaza (en el panel,
    rechazar borra la reseña) ni se vacía una respuesta.
  - Ticket (routes/soporte.py): cerrar = 'cerrado', reabrir = 'abierto', con
    fecha_actualizado = NOW(). La IA no responde tickets: responder envía un
    correo al cliente, que no se puede deshacer.
Nada se borra.
"""
from services.ia import buscador
from services.ia.texto import palabras
from services.ia_acciones import AccionAclarar, AccionError, _entero, _texto
from services.ia_acciones_crm import _sin_cambios, _snapshot

MAX_RESPUESTA = 1500
SIN_CORREO = 'La IA no envía correos al cliente por esto.'
_RELLENO_RESENA = ('resena', 'comentario', 'opinion', 'calificacion', 'cliente', 'sobre', 'dejo',
                   'hizo', 'escribio', 'producto')
_RELLENO_TICKET = ('ticket', 'caso', 'solicitud', 'soporte', 'cliente', 'sobre', 'abrio')


def _hay_tabla(cur, tabla):
    cur.execute('SELECT to_regclass(%s) AS t', (tabla,))
    return cur.fetchone()['t'] is not None


def _hay_columna(cur, tabla, columna):
    cur.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_schema = current_schema() AND table_name = %s AND column_name = %s""",
                (tabla, columna))
    return cur.fetchone() is not None


def _corto(texto, n=90):
    texto = ' '.join(str(texto or '').split())
    return texto if len(texto) <= n else texto[:n - 1] + '…'


def _elegir(cur, sql, texto_sql, filtro, referencia, relleno, que, etiqueta):
    """El registro nombrado; sin referencia, el único candidato o la lista para
    elegir por ID. Nunca adivina entre varios."""
    if referencia:
        filas, modo = buscador._por_palabras(cur, sql, '*', texto_sql, filtro, (), referencia, 5,
                                             ignorar=relleno)
        if not filas and not palabras(referencia, relleno):
            filas, modo = _todos(cur, sql, filtro)
    else:
        filas, modo = _todos(cur, sql, filtro)
    elegido = buscador.elegir(filas, modo)
    if elegido is not None:
        return elegido
    if not filas:
        raise AccionError(f'No encontré {que}.')
    lineas = [f"ID {f['id']} · {etiqueta(f)}" for f in filas[:5]]
    raise AccionAclarar(f'Encontré {len(filas) if len(filas) <= 5 else "varias"}: '
                        + '; '.join(lineas) + '. ¿Cuál es? Responde con su ID.')


def _todos(cur, sql, filtro):
    cur.execute(f'SELECT * FROM {sql} WHERE {filtro} ORDER BY id DESC LIMIT 6')
    return [dict(f) for f in cur.fetchall()], 'todas'


# ── Reseñas ────────────────────────────────────────────────────
def _resena_sql(con_respuesta):
    respuesta = 'c.respuesta' if con_respuesta else 'NULL::text'
    return ('SELECT c.id, c.autor_nombre, c.calificacion, c.comentario, '
            f'COALESCE(c.aprobado, FALSE) AS aprobado, {respuesta} AS respuesta, '
            'p.nombre AS producto FROM producto_comentarios c '
            'JOIN productos p ON p.id = c.producto_id')


def _etiqueta_resena(f):
    return f"{f['autor_nombre']} · {f['producto']} · {f['calificacion']}★ · «{_corto(f['comentario'], 50)}»"


def resena(cur, plan, pendiente, bloquear=False):
    """`pendiente`: solo las que faltan por aprobar (aprobar) o todas (responder)."""
    if not _hay_tabla(cur, 'producto_comentarios'):
        raise AccionError('Esta tienda todavía no tiene reseñas de clientes.')
    con_respuesta = _hay_columna(cur, 'producto_comentarios', 'respuesta')
    base = _resena_sql(con_respuesta)
    if plan.get('resena_id') is not None:
        rid = _entero(plan['resena_id'], 'el ID de la reseña')
        cur.execute(base + ' WHERE c.id = %s' + (' FOR UPDATE OF c' if bloquear else ''), (rid,))
        fila = cur.fetchone()
        if not fila:
            raise AccionAclarar(f'No encontré la reseña con el ID {rid}. ¿De qué cliente o producto es?')
        fila = dict(fila)
    else:
        referencia = _texto(plan.get('resena'), 'reseña', 200) or ''
        fila = _elegir(cur, f'({base}) r', "translate(lower(autor_nombre || ' ' || producto), %s, %s)",
                       'NOT aprobado' if pendiente else 'TRUE', referencia, _RELLENO_RESENA,
                       'una reseña por aprobar' + (f' como «{referencia}»' if referencia else '')
                       if pendiente else f'una reseña como «{referencia}»', _etiqueta_resena)
    if pendiente and fila['aprobado']:
        raise AccionError(f"La reseña de {fila['autor_nombre']} (ID {fila['id']}) ya está aprobada.")
    fila['_con_respuesta'] = con_respuesta
    return fila


def _detalles_resena(f):
    return [f"Reseña ID {f['id']} · {f['calificacion']}★", f"Cliente: {f['autor_nombre']}",
            f"Producto: {f['producto']}", f"Comentario: «{_corto(f['comentario'], 300)}»"]


def _preparar_aprobar(cur, plan):
    actual = resena(cur, plan, pendiente=True)
    payload = {'tipo': plan['tipo'], 'resena_id': actual['id'],
               'snapshot': _snapshot(actual, ('aprobado', 'comentario'))}
    detalles = _detalles_resena(actual) + ['Quedará visible en la página del producto.']
    return payload, f"Aprobar la reseña de {actual['autor_nombre']} sobre {actual['producto']}.", detalles


def _preparar_responder(cur, plan):
    respuesta = _texto(plan.get('respuesta'), 'texto de la respuesta', MAX_RESPUESTA, obligatorio=True)
    actual = resena(cur, plan, pendiente=False)
    if not actual['_con_respuesta']:
        raise AccionError('Esta tienda aún no permite responder reseñas. No se hizo ningún cambio.')
    if (actual['respuesta'] or '').strip() == respuesta:
        raise AccionError('Esa ya es la respuesta publicada; no hay cambios.')
    payload = {'tipo': plan['tipo'], 'resena_id': actual['id'], 'respuesta': respuesta,
               'snapshot': _snapshot(actual, ('respuesta', 'comentario'))}
    detalles = _detalles_resena(actual) + [f'Respuesta que se publicará: «{respuesta}»']
    if (actual['respuesta'] or '').strip():
        detalles.append(f"Reemplaza la respuesta actual: «{_corto(actual['respuesta'], 200)}»")
    detalles.append('Se verá en la página del producto, debajo del comentario.' if actual['aprobado']
                    else 'La reseña aún no está aprobada: la respuesta se verá cuando la apruebes.')
    return payload, f"Responder la reseña de {actual['autor_nombre']} sobre {actual['producto']}.", detalles


def _ejecutar_aprobar(cur, p, usuario):
    actual = resena(cur, {'resena_id': p['resena_id']}, pendiente=False, bloquear=True)
    _sin_cambios(actual, p.get('snapshot'), 'La reseña')
    cur.execute('UPDATE producto_comentarios SET aprobado = TRUE '
                'WHERE id = %s AND NOT COALESCE(aprobado, FALSE)', (actual['id'],))
    return {'mensaje': f"Reseña de {actual['autor_nombre']} aprobada: ya se ve en {actual['producto']}.",
            'resena_id': actual['id']}


def _ejecutar_responder(cur, p, usuario):
    actual = resena(cur, {'resena_id': p['resena_id']}, pendiente=False, bloquear=True)
    _sin_cambios(actual, p.get('snapshot'), 'La reseña')
    respuesta = _texto(p.get('respuesta'), 'texto de la respuesta', MAX_RESPUESTA, obligatorio=True)
    cur.execute('UPDATE producto_comentarios SET respuesta = %s, respuesta_fecha = NOW() WHERE id = %s',
                (respuesta, actual['id']))
    return {'mensaje': f"Respuesta publicada en la reseña de {actual['autor_nombre']}.",
            'resena_id': actual['id']}


# ── Tickets de soporte ─────────────────────────────────────────
_TICKET_SQL = ("SELECT t.id, t.asunto, t.estado, COALESCE(u.nombre, '') AS cliente "
               'FROM tickets_soporte t LEFT JOIN usuarios u ON u.id = t.usuario_id')


def _etiqueta_ticket(f):
    return f"{_corto(f['asunto'], 60)} · {f['cliente'] or 'sin cliente'} · {f['estado']}"


def ticket(cur, plan, cerrado, bloquear=False):
    """`cerrado`: False = uno abierto o respondido (para cerrar); True = uno cerrado (para reabrir)."""
    if not _hay_tabla(cur, 'tickets_soporte'):
        raise AccionError('Este negocio no usa el módulo de soporte.')
    if plan.get('ticket_id') is not None:
        tid = _entero(plan['ticket_id'], 'el ID del ticket')
        cur.execute(_TICKET_SQL + ' WHERE t.id = %s' + (' FOR UPDATE OF t' if bloquear else ''), (tid,))
        fila = cur.fetchone()
        if not fila:
            raise AccionAclarar(f'No encontré el ticket con el ID {tid}. ¿Cuál es su asunto?')
        fila = dict(fila)
        if not bloquear and (str(fila['estado']).lower() == 'cerrado') != cerrado:
            raise AccionError(f"El ticket ID {tid} no está cerrado (está {fila['estado']})." if cerrado
                              else f'El ticket ID {tid} ya está cerrado.')
        return fila
    referencia = _texto(plan.get('ticket'), 'ticket', 200) or ''
    filtro = "LOWER(estado) = 'cerrado'" if cerrado else "LOWER(estado) <> 'cerrado'"
    que = 'un ticket ' + ('cerrado' if cerrado else 'abierto') + (f' como «{referencia}»' if referencia else '')
    return _elegir(cur, f'({_TICKET_SQL}) k', "translate(lower(asunto || ' ' || cliente), %s, %s)",
                   filtro, referencia, _RELLENO_TICKET, que, _etiqueta_ticket)


def _preparar_ticket(cur, plan):
    cerrar = plan['tipo'] == 'cerrar_ticket'
    actual = ticket(cur, plan, cerrado=not cerrar)
    nuevo = 'cerrado' if cerrar else 'abierto'
    payload = {'tipo': plan['tipo'], 'ticket_id': actual['id'],
               'snapshot': _snapshot(actual, ('estado',))}
    detalles = [f"Ticket ID {actual['id']}: {_corto(actual['asunto'], 150)}",
                f"Cliente: {actual['cliente'] or '(sin cliente)'}",
                f"Estado: {actual['estado']} → {nuevo}", SIN_CORREO]
    verbo = 'Cerrar' if cerrar else 'Reabrir'
    return payload, f"{verbo} el ticket «{_corto(actual['asunto'], 60)}».", detalles


def _ejecutar_ticket(cur, p, usuario):
    cerrar = p['tipo'] == 'cerrar_ticket'
    actual = ticket(cur, {'ticket_id': p['ticket_id']}, cerrado=not cerrar, bloquear=True)
    _sin_cambios(actual, p.get('snapshot'), 'El ticket')
    fecha = ', fecha_actualizado = NOW()' if _hay_columna(cur, 'tickets_soporte', 'fecha_actualizado') else ''
    if cerrar:
        cur.execute(f"UPDATE tickets_soporte SET estado = 'cerrado'{fecha} "
                    "WHERE id = %s AND LOWER(estado) <> 'cerrado'", (actual['id'],))
    else:
        cur.execute(f"UPDATE tickets_soporte SET estado = 'abierto'{fecha} "
                    "WHERE id = %s AND LOWER(estado) = 'cerrado'", (actual['id'],))
    return {'mensaje': f"Ticket «{_corto(actual['asunto'], 60)}» {'cerrado' if cerrar else 'reabierto'}.",
            'ticket_id': actual['id']}


_PREPARAR = {
    'aprobar_resena': _preparar_aprobar,
    'responder_resena': _preparar_responder,
    'cerrar_ticket': _preparar_ticket,
    'reabrir_ticket': _preparar_ticket,
}
_EJECUTAR = {
    'aprobar_resena': _ejecutar_aprobar,
    'responder_resena': _ejecutar_responder,
    'cerrar_ticket': _ejecutar_ticket,
    'reabrir_ticket': _ejecutar_ticket,
}
TIPOS = tuple(_PREPARAR)


def preparar(cur, plan):
    return _PREPARAR[plan['tipo']](cur, plan)


def ejecutar(cur, fila, usuario):
    return _EJECUTAR[fila['tipo']](cur, fila['payload'], usuario)
