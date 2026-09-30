"""Acciones del panel sobre el CRM: tareas, actividades y oportunidades (fase 3
del CRUD de la IA).

Como en el catálogo, el motor (services/ia_acciones.py) interpreta, autoriza,
guarda la propuesta y confirma; aquí solo está la vista previa (preparar) y la
escritura al confirmar (ejecutar). Reglas replicadas de routes/crm.py:
  - Tarea: contacto, título, prioridad alta/media/baja (media por defecto),
    fecha límite opcional; completar = estado 'completada' + completada_en.
  - Actividad: contacto, tipo (llamada, email, reunión, WhatsApp, visita, nota,
    otro), asunto; fecha = ahora. Es historial: no se edita desde la IA.
  - Oportunidad: contacto, título, monto y etapa (prospecto por defecto);
    ganada/perdida ⇒ probabilidad 100/0 y fecha de cierre real.
  - Nada se borra: una tarea se completa; una oportunidad se marca perdida.
  - La IA no envía correos ni crea eventos de Google Calendar (el formulario del
    CRM sí lo hace); la vista previa lo dice.
Los valores de listas cerradas y las fechas los decide el servidor a partir de
las palabras de la persona («ganamos» = ganada, «mañana», «el viernes»).
"""
import re
from datetime import date, timedelta
from decimal import Decimal

from services.ia import buscador
from services.ia.texto import SIN_TILDES, normalizar, palabras
from services.ia_acciones import AccionAclarar, AccionError, _entero, _texto

PRIORIDADES = ('alta', 'media', 'baja')
TIPOS_ACTIVIDAD = ('llamada', 'email', 'reunion', 'whatsapp', 'visita', 'nota', 'otro')
ETAPAS = ('prospecto', 'calificado', 'propuesta', 'negociacion', 'ganada', 'perdida')
ETAPA_ETIQUETA = {'prospecto': 'Prospecto', 'calificado': 'Calificado', 'propuesta': 'Propuesta',
                  'negociacion': 'Negociación', 'ganada': 'Ganada', 'perdida': 'Perdida'}
SIN_AVISOS = 'La IA no envía correos ni crea eventos de calendario para esto.'

# ── Valores cerrados desde las palabras de la persona ──────────
_PRIORIDAD = (('alta', r'\b(urgente|alta|importante|prioritari[oa]|ya mismo|cuanto antes)\b'),
              ('baja', r'\b(baja|sin afan|cuando se pueda|no urgente)\b'))
_TIPO_ACTIVIDAD = (('llamada', r'\b(llam\w*|telefone\w*)\b'), ('whatsapp', r'\bwhats?app\w*\b'),
                   ('email', r'\b(correo|email|e-mail|mail)\b'), ('reunion', r'\b(reuni\w*)\b'),
                   ('visita', r'\b(visit\w*)\b'), ('nota', r'\b(nota|anota\w*|apunta\w*)\b'))
_ETAPA = (('ganada', r'\b(ganad[ao]|ganamos|gano|cerramos|cerrad[ao]|se cerro|vendimos)\b'),
          ('perdida', r'\b(perdid[ao]|perdimos|se cayo|se perdio|no se dio|descartad[ao])\b'),
          ('negociacion', r'\b(negociacion|negociando|negociar)\b'),
          ('propuesta', r'\b(propuesta|cotizacion|cotizad[ao]|cotizamos)\b'),
          ('calificado', r'\b(calificad[ao]|interesad[ao])\b'),
          ('prospecto', r'\b(prospecto)\b'))


def _de_palabras(opciones, texto):
    plano = normalizar(texto)
    for valor, patron in opciones:
        if re.search(patron, plano):
            return valor
    return None


def prioridad_de(texto):
    return _de_palabras(_PRIORIDAD, texto)


def tipo_actividad_de(texto):
    return _de_palabras(_TIPO_ACTIVIDAD, texto)


def etapa_de(texto):
    return _de_palabras(_ETAPA, texto)


# ── Fechas dichas por la persona ───────────────────────────────
_DIAS = {'lunes': 0, 'martes': 1, 'miercoles': 2, 'jueves': 3, 'viernes': 4, 'sabado': 5,
         'domingo': 6}
_MESES = {m: i + 1 for i, m in enumerate(('enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
                                          'julio', 'agosto', 'septiembre', 'octubre',
                                          'noviembre', 'diciembre'))}
_MESES['setiembre'] = 9


def fecha_de(expresion, hoy=None):
    """«hoy», «mañana», «pasado mañana», «en 3 días», «el viernes», «el 15»,
    «15 de octubre», «2026-10-15» o «15/10» → date; None si no se entiende."""
    hoy = hoy or date.today()
    t = normalizar(expresion).strip()
    if not t:
        return None
    if re.search(r'\bpasado manana\b', t):
        return hoy + timedelta(days=2)
    if re.search(r'\bmanana\b', t):
        return hoy + timedelta(days=1)
    if re.search(r'\bhoy\b', t):
        return hoy
    m = re.search(r'\ben (\d{1,3}) dias?\b', t)
    if m:
        return hoy + timedelta(days=int(m.group(1)))
    m = re.search(r'\b(\d{4})-(\d{1,2})-(\d{1,2})\b', t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r'\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b', t)
    if m:
        anio = int(m.group(3)) if m.group(3) else hoy.year
        anio = anio + 2000 if anio < 100 else anio
        try:
            fecha = date(anio, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
        return fecha if m.group(3) or fecha >= hoy else date(anio + 1, fecha.month, fecha.day)
    m = re.search(r'\b(\d{1,2}) de (' + '|'.join(_MESES) + r')\b', t)
    if m:
        try:
            fecha = date(hoy.year, _MESES[m.group(2)], int(m.group(1)))
        except ValueError:
            return None
        return fecha if fecha >= hoy else fecha.replace(year=hoy.year + 1)
    for nombre, numero in _DIAS.items():
        if re.search(rf'\b{nombre}\b', t):
            dias = (numero - hoy.weekday()) % 7 or 7
            return hoy + timedelta(days=dias)
    m = re.search(r'\bel (\d{1,2})\b', t)
    if m:
        dia = int(m.group(1))
        mes, anio = (hoy.month, hoy.year) if dia >= hoy.day else (
            (hoy.month % 12) + 1, hoy.year + (hoy.month == 12))
        try:
            return date(anio, mes, dia)
        except ValueError:
            return None
    return None


def _fecha(valor, que='la fecha'):
    if valor in (None, ''):
        return None
    fecha = fecha_de(str(valor))
    if fecha is None:
        raise AccionAclarar(f'No entendí {que} «{valor}». ¿Qué día es? (p. ej. «mañana», '
                            '«el viernes», «15 de octubre»)')
    return fecha


def _monto(valor):
    if valor in (None, ''):
        return None
    from services.ia_acciones_catalogo import _monto as monto
    return monto(valor, 'monto estimado')


def _pesos(numero):
    from helpers import formatear_moneda
    return formatear_moneda(float(numero or 0))


# ── Registros ──────────────────────────────────────────────────
def _contacto(cur, plan):
    from services.ia_acciones import _contacto as contacto
    return contacto(cur, plan)


def _por_palabras(cur, sql_base, texto_sql, referencia, filtro_params=()):
    """Busca por palabras en el título y el nombre del contacto; devuelve la
    fila elegida o lanza la aclaración con opciones."""
    buscar = [p for p in palabras(referencia)
              if p not in ('tarea', 'oportunidad', 'negocio', 'recordatorio', 'trato')]
    if not buscar:
        return [], 'ninguno'
    puntos = ' + '.join(f'(CASE WHEN {texto_sql} LIKE %s THEN 1 ELSE 0 END)' for _ in buscar)
    params = []
    for p in buscar:
        params += [*SIN_TILDES, f'%{p}%']
    cur.execute(f'SELECT * FROM (SELECT x.*, ({puntos}) AS puntos FROM ({sql_base}) x) y '
                'WHERE puntos > 0 ORDER BY puntos DESC, id DESC LIMIT 6',
                (*params, *filtro_params))
    filas = [dict(f) for f in cur.fetchall()]
    for f in filas:
        f['palabras'] = len(buscar)
    todas = [f for f in filas if f['puntos'] == len(buscar)]
    return (todas, 'todas') if todas else ((filas, 'parcial') if filas else ([], 'ninguno'))


def _elegir(filas, modo, que, etiqueta):
    elegido = buscador.elegir(filas, modo)
    if elegido is not None:
        return elegido
    if not filas:
        raise AccionAclarar(f'No encontré {que}. ¿Cuál es? Dime su título o su ID.')
    lineas = [f"ID {f['id']} · {f['titulo']} · {etiqueta(f)}" for f in filas[:5]]
    raise AccionAclarar(f'Encontré varias: ' + '; '.join(lineas) + '. ¿Cuál es? Responde con su ID.')


_TAREA_SQL = ('SELECT t.id, t.titulo, t.prioridad, t.estado, t.fecha_limite, t.descripcion, '
              't.contacto_id, c.nombre AS contacto FROM crm_tareas t '
              'JOIN crm_contactos c ON c.id = t.contacto_id WHERE t.estado = %s')
_TAREA_TEXTO = "translate(lower(titulo || ' ' || contacto), %s, %s)"


def tarea(cur, plan, estado='pendiente', bloquear=False):
    if plan.get('tarea_id') is not None:
        tid = _entero(plan['tarea_id'], 'el ID de la tarea')
        cur.execute(_TAREA_SQL.replace('WHERE t.estado = %s', 'WHERE t.id = %s')
                    + (' FOR UPDATE OF t' if bloquear else ''), (tid,))
        fila = cur.fetchone()
        if not fila or fila['estado'] != estado:
            raise AccionAclarar(f'No encontré una tarea {estado} con el ID {tid}. ¿Cuál es su título?')
        return dict(fila)
    referencia = _texto(plan.get('tarea'), 'tarea', 200, obligatorio=True)
    filas, modo = _por_palabras(cur, _TAREA_SQL, _TAREA_TEXTO, referencia, (estado,))
    return _elegir(filas, modo, f'una tarea {estado} como «{referencia}»',
                   lambda f: f"{f['contacto']}" + (f" · vence {f['fecha_limite']}" if f['fecha_limite'] else ''))


_OPORTUNIDAD_SQL = ('SELECT o.id, o.titulo, o.etapa, o.monto_estimado, o.probabilidad, '
                    'o.fecha_cierre_est, o.descripcion, o.contacto_id, c.nombre AS contacto '
                    'FROM crm_oportunidades o JOIN crm_contactos c ON c.id = o.contacto_id')
_OPORTUNIDAD_TEXTO = "translate(lower(titulo || ' ' || contacto), %s, %s)"


def oportunidad(cur, plan, bloquear=False):
    if plan.get('oportunidad_id') is not None:
        oid = _entero(plan['oportunidad_id'], 'el ID de la oportunidad')
        cur.execute(_OPORTUNIDAD_SQL + ' WHERE o.id = %s' + (' FOR UPDATE OF o' if bloquear else ''),
                    (oid,))
        fila = cur.fetchone()
        if not fila:
            raise AccionAclarar(f'No encontré la oportunidad con el ID {oid}. ¿Cuál es su título?')
        return dict(fila)
    referencia = _texto(plan.get('oportunidad'), 'oportunidad', 200, obligatorio=True)
    filas, modo = _por_palabras(cur, _OPORTUNIDAD_SQL, _OPORTUNIDAD_TEXTO, referencia)
    return _elegir(filas, modo, f'una oportunidad como «{referencia}»',
                   lambda f: f"{f['contacto']} · {ETAPA_ETIQUETA.get(f['etapa'], f['etapa'])}")


def _plano(valor):
    if isinstance(valor, (Decimal, float, int)) and not isinstance(valor, bool):
        return format(Decimal(str(valor)).normalize(), 'f')
    return None if valor is None else str(valor)


def _snapshot(fila, claves):
    return {k: _plano(fila.get(k)) for k in claves}


def _sin_cambios(fila, snapshot, que):
    if any(_plano(fila.get(k)) != v for k, v in (snapshot or {}).items()):
        raise AccionError(f'{que} cambió desde la vista previa. Prepara una nueva propuesta.')


# ── Vista previa ───────────────────────────────────────────────
def preparar(cur, plan):
    return _PREPARAR[plan['tipo']](cur, plan)


def _preparar_crear_tarea(cur, plan):
    contacto = _contacto(cur, plan)
    titulo = _texto(plan.get('titulo'), 'título de la tarea', 300, obligatorio=True)
    prioridad = plan.get('prioridad') or 'media'
    if prioridad not in PRIORIDADES:
        raise AccionAclarar('¿Qué prioridad tiene: alta, media o baja?')
    fecha = _fecha(plan.get('fecha'), 'la fecha límite')
    descripcion = _texto(plan.get('descripcion'), 'descripción', 2000)
    payload = {'tipo': 'crear_tarea', 'contacto_id': contacto['id'], 'titulo': titulo,
               'prioridad': prioridad, 'fecha_limite': fecha.isoformat() if fecha else None,
               'descripcion': descripcion}
    detalles = [f"Contacto: {contacto['nombre']} (ID {contacto['id']})", f'Tarea: {titulo}',
                f'Prioridad: {prioridad}',
                f'Vence: {fecha.isoformat()}' if fecha else 'Sin fecha límite']
    if descripcion:
        detalles.append(f'Detalle: {descripcion}')
    detalles.append(SIN_AVISOS)
    return payload, f"Crear tarea «{titulo}» para {contacto['nombre']}.", detalles


def _preparar_estado_tarea(cur, plan):
    completar = plan['tipo'] == 'completar_tarea'
    actual = tarea(cur, plan, estado='pendiente' if completar else 'completada')
    payload = {'tipo': plan['tipo'], 'tarea_id': actual['id'],
               'snapshot': _snapshot(actual, ('titulo', 'estado'))}
    detalles = [f"Tarea: {actual['titulo']} (ID {actual['id']})", f"Contacto: {actual['contacto']}"]
    if completar:
        return payload, f"Marcar como hecha la tarea «{actual['titulo']}».", detalles
    return payload, f"Reabrir la tarea «{actual['titulo']}».", detalles + ['Vuelve a quedar pendiente.']


def _preparar_editar_tarea(cur, plan):
    cambios = plan.get('cambios')
    if not isinstance(cambios, dict) or not cambios:
        raise AccionAclarar('¿Qué quieres cambiar de la tarea (título, prioridad, fecha o detalle)?')
    actual = tarea(cur, plan)
    nuevos, detalles = {}, [f"Tarea: {actual['titulo']} (ID {actual['id']}) · {actual['contacto']}"]
    for campo, valor in cambios.items():
        if campo == 'titulo':
            nuevos['titulo'] = _texto(valor, 'título', 300, obligatorio=True)
            detalles.append(f"Título: {actual['titulo']} → {nuevos['titulo']}")
        elif campo == 'prioridad':
            if valor not in PRIORIDADES:
                raise AccionAclarar('¿Qué prioridad: alta, media o baja?')
            nuevos['prioridad'] = valor
            detalles.append(f"Prioridad: {actual['prioridad']} → {valor}")
        elif campo == 'fecha':
            fecha = _fecha(valor, 'la fecha límite')
            nuevos['fecha_limite'] = fecha.isoformat()
            detalles.append(f"Vence: {actual['fecha_limite'] or '(sin fecha)'} → {fecha.isoformat()}")
        elif campo == 'descripcion':
            nuevos['descripcion'] = _texto(valor, 'descripción', 2000)
            detalles.append('Detalle: ' + (nuevos['descripcion'] or '(vacío)'))
        else:
            raise AccionError('La solicitud incluye campos de tarea no permitidos.')
    nuevos = {k: v for k, v in nuevos.items() if _plano(v) != _plano(actual.get(k))}
    if not nuevos:
        raise AccionError('Los datos indicados ya son los actuales; no hay cambios.')
    payload = {'tipo': 'editar_tarea', 'tarea_id': actual['id'], 'cambios': nuevos,
               'snapshot': _snapshot(actual, ('titulo', 'prioridad', 'fecha_limite', 'descripcion',
                                              'estado'))}
    return payload, f"Editar la tarea «{actual['titulo']}».", detalles + [SIN_AVISOS]


def _preparar_actividad(cur, plan):
    contacto = _contacto(cur, plan)
    tipo = plan.get('tipo_actividad')
    if tipo not in TIPOS_ACTIVIDAD:
        raise AccionAclarar('¿Qué fue: llamada, correo, reunión, WhatsApp, visita o nota?')
    asunto = _texto(plan.get('asunto'), 'asunto', 300, obligatorio=True)
    descripcion = _texto(plan.get('descripcion'), 'descripción', 2000)
    payload = {'tipo': 'registrar_actividad', 'contacto_id': contacto['id'], 'tipo_actividad': tipo,
               'asunto': asunto, 'descripcion': descripcion}
    detalles = [f"Contacto: {contacto['nombre']} (ID {contacto['id']})", f'Tipo: {tipo}',
                f'Asunto: {asunto}', 'Fecha: ahora']
    if descripcion:
        detalles.append(f'Detalle: {descripcion}')
    return payload, f"Registrar {tipo} con {contacto['nombre']}: {asunto}.", detalles + [SIN_AVISOS]


def _preparar_crear_oportunidad(cur, plan):
    contacto = _contacto(cur, plan)
    titulo = _texto(plan.get('titulo'), 'título de la oportunidad', 200, obligatorio=True)
    etapa = plan.get('etapa') or 'prospecto'
    if etapa not in ETAPAS:
        raise AccionAclarar('¿En qué etapa va: prospecto, calificado, propuesta, negociación, '
                            'ganada o perdida?')
    monto = _monto(plan.get('monto'))
    cierre = _fecha(plan.get('fecha_cierre'), 'la fecha de cierre')
    probabilidad = {'ganada': 100, 'perdida': 0}.get(etapa, 50)
    payload = {'tipo': 'crear_oportunidad', 'contacto_id': contacto['id'], 'titulo': titulo,
               'etapa': etapa, 'monto': str(monto) if monto is not None else None,
               'probabilidad': probabilidad, 'fecha_cierre': cierre.isoformat() if cierre else None}
    detalles = [f"Contacto: {contacto['nombre']} (ID {contacto['id']})", f'Oportunidad: {titulo}',
                f"Etapa: {ETAPA_ETIQUETA[etapa]} (probabilidad {probabilidad} %)",
                f'Monto estimado: {_pesos(monto)}' if monto is not None else 'Sin monto estimado']
    if cierre:
        detalles.append(f'Cierre estimado: {cierre.isoformat()}')
    return payload, f"Crear oportunidad «{titulo}» con {contacto['nombre']}.", detalles


def _preparar_mover_oportunidad(cur, plan):
    etapa = plan.get('etapa')
    if etapa not in ETAPAS:
        raise AccionAclarar('¿A qué etapa pasa: prospecto, calificado, propuesta, negociación, '
                            'ganada o perdida?')
    actual = oportunidad(cur, plan)
    if actual['etapa'] == etapa:
        raise AccionError(f"La oportunidad ya está en {ETAPA_ETIQUETA[etapa]}.")
    motivo = _texto(plan.get('motivo_perdida'), 'motivo', 160) if etapa == 'perdida' else None
    payload = {'tipo': 'mover_oportunidad', 'oportunidad_id': actual['id'], 'etapa': etapa,
               'motivo_perdida': motivo,
               'snapshot': _snapshot(actual, ('titulo', 'etapa', 'monto_estimado'))}
    detalles = [f"Oportunidad: {actual['titulo']} (ID {actual['id']}) · {actual['contacto']}",
                f"Etapa: {ETAPA_ETIQUETA.get(actual['etapa'], actual['etapa'])} → {ETAPA_ETIQUETA[etapa]}"]
    if etapa in ('ganada', 'perdida'):
        detalles.append(f"Probabilidad → {100 if etapa == 'ganada' else 0} %; se registra la "
                        'fecha de cierre de hoy.')
    if motivo:
        detalles.append(f'Motivo: {motivo}')
    return payload, (f"Pasar «{actual['titulo']}» a {ETAPA_ETIQUETA[etapa]}."), detalles


def _preparar_editar_oportunidad(cur, plan):
    cambios = plan.get('cambios')
    if not isinstance(cambios, dict) or not cambios:
        raise AccionAclarar('¿Qué quieres cambiar de la oportunidad (título, monto, fecha de '
                            'cierre o detalle)?')
    actual = oportunidad(cur, plan)
    nuevos, detalles = {}, [f"Oportunidad: {actual['titulo']} (ID {actual['id']}) · {actual['contacto']}"]
    for campo, valor in cambios.items():
        if campo == 'titulo':
            nuevos['titulo'] = _texto(valor, 'título', 200, obligatorio=True)
            detalles.append(f"Título: {actual['titulo']} → {nuevos['titulo']}")
        elif campo == 'monto':
            monto = _monto(valor)
            nuevos['monto_estimado'] = monto
            detalles.append(f"Monto: {_pesos(actual['monto_estimado'])} → {_pesos(monto)}")
        elif campo == 'fecha_cierre':
            fecha = _fecha(valor, 'la fecha de cierre')
            nuevos['fecha_cierre_est'] = fecha.isoformat()
            detalles.append(f"Cierre estimado → {fecha.isoformat()}")
        elif campo == 'descripcion':
            nuevos['descripcion'] = _texto(valor, 'descripción', 2000)
            detalles.append('Detalle: ' + (nuevos['descripcion'] or '(vacío)'))
        else:
            raise AccionError('La solicitud incluye campos de oportunidad no permitidos. '
                              'Para cambiar la etapa di «pasa la oportunidad … a negociación».')
    nuevos = {k: v for k, v in nuevos.items() if _plano(v) != _plano(actual.get(k))}
    if not nuevos:
        raise AccionError('Los datos indicados ya son los actuales; no hay cambios.')
    payload = {'tipo': 'editar_oportunidad', 'oportunidad_id': actual['id'],
               'cambios': {k: (str(v) if isinstance(v, Decimal) else v) for k, v in nuevos.items()},
               'snapshot': _snapshot(actual, ('titulo', 'etapa', 'monto_estimado',
                                              'fecha_cierre_est', 'descripcion'))}
    return payload, f"Editar la oportunidad «{actual['titulo']}».", detalles


_PREPARAR = {
    'crear_tarea': _preparar_crear_tarea,
    'completar_tarea': _preparar_estado_tarea,
    'reabrir_tarea': _preparar_estado_tarea,
    'editar_tarea': _preparar_editar_tarea,
    'registrar_actividad': _preparar_actividad,
    'crear_oportunidad': _preparar_crear_oportunidad,
    'mover_oportunidad': _preparar_mover_oportunidad,
    'editar_oportunidad': _preparar_editar_oportunidad,
}
TIPOS = tuple(_PREPARAR)


# ── Escritura al confirmar ─────────────────────────────────────
def ejecutar(cur, fila, usuario):
    return _EJECUTAR[fila['tipo']](cur, fila['payload'], usuario)


def _contacto_activo(cur, cid):
    cur.execute('SELECT id, nombre FROM crm_contactos WHERE id = %s AND activo = TRUE', (cid,))
    fila = cur.fetchone()
    if not fila:
        raise AccionError('El contacto ya no está activo. Prepara una nueva propuesta.')
    return fila


def _ejecutar_crear_tarea(cur, p, usuario):
    contacto = _contacto_activo(cur, p['contacto_id'])
    cur.execute("""INSERT INTO crm_tareas (contacto_id, titulo, descripcion, prioridad,
                                           fecha_limite, creado_por)
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                (contacto['id'], p['titulo'], p.get('descripcion'), p['prioridad'],
                 p.get('fecha_limite'), usuario))
    tid = int(cur.fetchone()['id'])
    return {'mensaje': f"Tarea «{p['titulo']}» creada para {contacto['nombre']} (ID {tid}).",
            'tarea_id': tid}


def _ejecutar_estado_tarea(cur, p, usuario):
    completar = p['tipo'] == 'completar_tarea'
    actual = tarea(cur, {'tarea_id': p['tarea_id']},
                   estado='pendiente' if completar else 'completada', bloquear=True)
    _sin_cambios(actual, p.get('snapshot'), 'La tarea')
    if completar:
        cur.execute("UPDATE crm_tareas SET estado = 'completada', completada_en = CURRENT_TIMESTAMP "
                    "WHERE id = %s AND estado = 'pendiente'", (actual['id'],))
        return {'mensaje': f"Tarea «{actual['titulo']}» marcada como hecha.", 'tarea_id': actual['id']}
    cur.execute("UPDATE crm_tareas SET estado = 'pendiente', completada_en = NULL "
                "WHERE id = %s AND estado = 'completada'", (actual['id'],))
    return {'mensaje': f"Tarea «{actual['titulo']}» reabierta.", 'tarea_id': actual['id']}


def _ejecutar_editar_tarea(cur, p, usuario):
    actual = tarea(cur, {'tarea_id': p['tarea_id']}, bloquear=True)
    _sin_cambios(actual, p.get('snapshot'), 'La tarea')
    asignaciones = ', '.join(f'{k} = %s' for k in p['cambios'])
    cur.execute(f'UPDATE crm_tareas SET {asignaciones} WHERE id = %s',
                (*p['cambios'].values(), actual['id']))
    return {'mensaje': f"Tarea «{actual['titulo']}» actualizada.", 'tarea_id': actual['id']}


def _ejecutar_actividad(cur, p, usuario):
    contacto = _contacto_activo(cur, p['contacto_id'])
    cur.execute("""INSERT INTO crm_actividades (contacto_id, tipo, asunto, descripcion,
                                                fecha_actividad, usuario_id)
                   VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, %s) RETURNING id""",
                (contacto['id'], p['tipo_actividad'], p['asunto'], p.get('descripcion'), usuario))
    aid = int(cur.fetchone()['id'])
    return {'mensaje': f"{p['tipo_actividad'].capitalize()} registrada con {contacto['nombre']} (ID {aid}).",
            'actividad_id': aid, 'contacto_id': contacto['id']}


def _ejecutar_crear_oportunidad(cur, p, usuario):
    contacto = _contacto_activo(cur, p['contacto_id'])
    cierre_real = 'CURRENT_DATE' if p['etapa'] in ('ganada', 'perdida') else 'NULL'
    cur.execute(f"""INSERT INTO crm_oportunidades
                        (contacto_id, titulo, monto_estimado, probabilidad, etapa,
                         fecha_cierre_est, fecha_cierre_real)
                    VALUES (%s, %s, %s, %s, %s, %s, {cierre_real}) RETURNING id""",
                (contacto['id'], p['titulo'], Decimal(p['monto']) if p.get('monto') else 0,
                 p['probabilidad'], p['etapa'], p.get('fecha_cierre')))
    oid = int(cur.fetchone()['id'])
    return {'mensaje': f"Oportunidad «{p['titulo']}» creada con {contacto['nombre']} (ID {oid}).",
            'oportunidad_id': oid}


def _ejecutar_mover_oportunidad(cur, p, usuario):
    actual = oportunidad(cur, {'oportunidad_id': p['oportunidad_id']}, bloquear=True)
    _sin_cambios(actual, p.get('snapshot'), 'La oportunidad')
    sets, valores = ['etapa = %s', 'updated_at = NOW()'], [p['etapa']]
    if p['etapa'] in ('ganada', 'perdida'):
        sets += ['fecha_cierre_real = COALESCE(fecha_cierre_real, CURRENT_DATE)',
                 f"probabilidad = {100 if p['etapa'] == 'ganada' else 0}"]
    if p.get('motivo_perdida'):
        sets.append('motivo_perdida = %s')
        valores.append(p['motivo_perdida'])
    cur.execute(f"UPDATE crm_oportunidades SET {', '.join(sets)} WHERE id = %s",
                (*valores, actual['id']))
    return {'mensaje': f"«{actual['titulo']}» pasó a {ETAPA_ETIQUETA[p['etapa']]}.",
            'oportunidad_id': actual['id']}


def _ejecutar_editar_oportunidad(cur, p, usuario):
    actual = oportunidad(cur, {'oportunidad_id': p['oportunidad_id']}, bloquear=True)
    _sin_cambios(actual, p.get('snapshot'), 'La oportunidad')
    valores = {k: (Decimal(v) if k == 'monto_estimado' and v is not None else v)
               for k, v in p['cambios'].items()}
    asignaciones = ', '.join(f'{k} = %s' for k in valores)
    cur.execute(f'UPDATE crm_oportunidades SET {asignaciones}, updated_at = NOW() WHERE id = %s',
                (*valores.values(), actual['id']))
    return {'mensaje': f"Oportunidad «{actual['titulo']}» actualizada.", 'oportunidad_id': actual['id']}


_EJECUTAR = {
    'crear_tarea': _ejecutar_crear_tarea,
    'completar_tarea': _ejecutar_estado_tarea,
    'reabrir_tarea': _ejecutar_estado_tarea,
    'editar_tarea': _ejecutar_editar_tarea,
    'registrar_actividad': _ejecutar_actividad,
    'crear_oportunidad': _ejecutar_crear_oportunidad,
    'mover_oportunidad': _ejecutar_mover_oportunidad,
    'editar_oportunidad': _ejecutar_editar_oportunidad,
}
