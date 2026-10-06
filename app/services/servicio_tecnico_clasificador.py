"""Servicio Técnico: clasificación de cada orden para el historial.

Con la falla que reportó el cliente, el diagnóstico, la solución y las piezas
cambiadas se guarda en la orden:
  falla_categoria     tipo de falla (lista cerrada, FALLAS)
  componente          pieza afectada (lista cerrada, COMPONENTES)
  solucion_categoria  tipo de solución (lista cerrada, SOLUCIONES)
  etiquetas           palabras clave para buscar
  resumen_caso        «problema → solución» en una frase
  clasificacion_fuente  'reglas' (sin IA) | 'ia' | 'manual'

Primero clasifican las REGLAS (siempre funcionan, sin IA). Si la IA está
disponible, propone sobre la misma lista cerrada y se valida: un valor fuera de
la lista se descarta y queda el de las reglas. A la IA solo le llega
información técnica del equipo (nunca nombre, teléfono, correo ni clave).
Una clasificación 'manual' (la eligió el técnico) no la pisa nadie.
"""

import json
import re
import threading
import unicodedata

from flask import current_app

from database import get_db_cursor

FALLAS = [
    ('no_enciende', 'No enciende / no da imagen'),
    ('pantalla', 'Pantalla / display'),
    ('bateria_carga', 'Batería / no carga'),
    ('lentitud', 'Lentitud / rendimiento'),
    ('software', 'Sistema operativo / programas'),
    ('virus', 'Virus / publicidad / malware'),
    ('sobrecalentamiento', 'Se calienta / ventilador'),
    ('teclado_touch', 'Teclado / mouse / táctil'),
    ('audio', 'Audio / micrófono / parlante'),
    ('conectividad', 'Wi-Fi / Bluetooth / red / señal'),
    ('almacenamiento', 'Disco / almacenamiento / datos'),
    ('liquido', 'Daño por líquido / humedad'),
    ('fisico', 'Golpe / daño físico / carcasa'),
    ('camara', 'Cámara'),
    ('puertos', 'Puertos / USB / HDMI'),
    ('impresion', 'Impresión'),
    ('energia', 'Energía / UPS / regulador'),
    ('cuenta_bloqueo', 'Contraseña / cuenta / bloqueo'),
    ('mantenimiento', 'Mantenimiento preventivo'),
    ('otro', 'Otra falla'),
]
COMPONENTES = [
    ('pantalla', 'Pantalla'), ('bateria', 'Batería'), ('cargador', 'Cargador'), ('pin_carga', 'Pin de carga'),
    ('disco', 'Disco / almacenamiento'), ('ram', 'Memoria RAM'), ('board', 'Board / placa base'),
    ('teclado', 'Teclado'), ('ventilador', 'Ventilador / disipador'), ('fuente', 'Fuente de poder'),
    ('sistema', 'Sistema operativo'), ('camara', 'Cámara'), ('audio', 'Parlante / micrófono'),
    ('puerto', 'Puerto / conector'), ('flex', 'Flex / bisagra'), ('impresora', 'Mecanismo de impresión'),
    ('baterias_ups', 'Baterías de UPS'), ('ninguno', 'Ninguna pieza'), ('otro', 'Otra pieza'),
]
SOLUCIONES = [
    ('cambio_pieza', 'Cambio de pieza'),
    ('reparacion_board', 'Reparación de board / soldadura'),
    ('limpieza', 'Limpieza / mantenimiento'),
    ('reinstalacion', 'Formateo / reinstalación del sistema'),
    ('configuracion', 'Configuración / actualización / drivers'),
    ('virus', 'Eliminación de virus'),
    ('recuperacion_datos', 'Recuperación de datos'),
    ('mejora', 'Mejora (RAM / SSD)'),
    ('desbloqueo', 'Desbloqueo / cuenta'),
    ('sin_reparacion', 'No se reparó'),
    ('diagnostico', 'Solo diagnóstico'),
    ('otro', 'Otra solución'),
]
NOMBRE_FALLA = dict(FALLAS)
NOMBRE_COMPONENTE = dict(COMPONENTES)
NOMBRE_SOLUCION = dict(SOLUCIONES)

# Palabras (sin tildes, en minúscula) que delatan cada categoría. El orden importa:
# gana la primera falla con más coincidencias; los empates los rompe este orden.
_REGLAS_FALLA = [
    ('liquido', ('mojo', 'mojado', 'agua', 'liquido', 'humedad', 'cafe encima', 'se le rego', 'sulfat')),
    ('virus', ('virus', 'malware', 'publicidad', 'ventanas emergentes', 'troyano', 'ransomware')),
    ('cuenta_bloqueo', ('contrasena', 'clave olvid', 'olvido la clave', 'olvido el patron', 'olvido el pin',
                        'olvido la contrasena', 'patron', 'bloqueado', 'bloqueo', 'frp', 'icloud',
                        'cuenta google')),
    ('no_enciende', ('no enciende', 'no prende', 'no arranca', 'no da imagen', 'no da video', 'muerto',
                     'no hace nada', 'no carga el sistema', 'se apaga solo', 'se reinicia')),
    ('pantalla', ('pantalla', 'display', 'lcd', 'tactil roto', 'vidrio', 'rayas en la pantalla', 'lineas',
                  'manchas', 'sin imagen', 'parpadea', 'retroiluminacion', 'flex de video')),
    ('bateria_carga', ('no carga', 'bateria', 'se descarga', 'pin de carga', 'puerto de carga', 'cargador',
                       'dura poco la carga', 'carga lento')),
    ('sobrecalentamiento', ('se calienta', 'calienta', 'temperatura', 'ventilador', 'ruido del ventilador',
                            'pasta termica', 'sobrecalent')),
    ('lentitud', ('lento', 'lentitud', 'se pega', 'se congela', 'se traba', 'demora', 'rendimiento')),
    ('software', ('windows', 'no inicia el sistema', 'pantallazo azul', 'error', 'actualizacion', 'programa',
                  'office', 'driver', 'controlador', 'sistema operativo', 'android', 'ios', 'aplicacion')),
    ('almacenamiento', ('disco', 'ssd', 'hdd', 'almacenamiento', 'memoria llena', 'perdio informacion',
                        'recuperar datos', 'recuperar informacion', 'archivos borrados')),
    ('teclado_touch', ('teclado', 'tecla', 'touchpad', 'mouse', 'touch', 'tactil')),
    ('audio', ('audio', 'sonido', 'parlante', 'microfono', 'auricular', 'no suena', 'no se escucha')),
    ('conectividad', ('wifi', 'wi-fi', 'internet', 'bluetooth', 'red', 'senal', 'no conecta', 'sim')),
    ('camara', ('camara',)),
    ('puertos', ('usb', 'hdmi', 'puerto', 'conector', 'jack')),
    ('impresion', ('imprime', 'impresion', 'atasco', 'papel', 'cartucho', 'tinta', 'cabezal', 'toner')),
    ('energia', ('ups', 'regulador', 'pita', 'autonomia', 'baterias de la ups', 'sin luz')),
    ('fisico', ('golpe', 'se cayo', 'caida', 'quebr', 'partido', 'roto', 'bisagra', 'carcasa', 'tapa')),
    ('mantenimiento', ('mantenimiento', 'limpieza', 'revision general', 'preventivo')),
]
_REGLAS_SOLUCION = [
    ('sin_reparacion', ('no tiene arreglo', 'no se reparo', 'no se pudo', 'sin reparacion', 'no aprobo',
                        'no acepto', 'se devuelve sin', 'irreparable', 'no hay repuesto')),
    ('recuperacion_datos', ('recuper', 'respaldo de informacion', 'backup')),
    ('virus', ('virus', 'antivirus', 'malware', 'desinfec')),
    ('desbloqueo', ('desbloque', 'quite la cuenta', 'restablecer contrasena', 'frp', 'reseteo de cuenta')),
    ('mejora', ('ampli', 'mejora', 'upgrade', 'se agrego memoria', 'se instalo ssd', 'migracion a ssd', 'clon')),
    ('reparacion_board', ('board', 'soldad', 'reball', 'microsoldadura', 'corto', 'componente smd', 'integrado')),
    ('reinstalacion', ('formate', 'reinstal', 'instalacion de windows', 'instale windows', 'restauracion de fabrica',
                       'reset de fabrica', 'flasheo', 'flashe')),
    ('cambio_pieza', ('cambio', 'cambie', 'reemplaz', 'se instalo', 'nueva pieza', 'repuesto', 'se monto')),
    ('limpieza', ('limpieza', 'se limpio', 'limpiamos', 'pasta termica', 'mantenimiento', 'sopletea', 'aspir')),
    ('configuracion', ('configur', 'actualiz', 'driver', 'controlador', 'ajust', 'instal programa', 'office')),
    ('diagnostico', ('solo diagnostico', 'diagnostico entregado', 'revision sin costo')),
]
_REGLAS_COMPONENTE = [
    ('baterias_ups', ('baterias de la ups', 'baterias ups', 'bateria de ups')),
    ('pin_carga', ('pin de carga', 'puerto de carga', 'conector de carga')),
    ('pantalla', ('pantalla', 'display', 'lcd', 'vidrio', 'tactil')),
    ('bateria', ('bateria',)),
    ('cargador', ('cargador',)),
    ('disco', ('disco', 'ssd', 'hdd', 'almacenamiento', 'nvme')),
    ('ram', ('ram', 'memoria')),
    ('board', ('board', 'placa', 'tarjeta madre', 'motherboard')),
    ('teclado', ('teclado', 'tecla')),
    ('ventilador', ('ventilador', 'disipador', 'pasta termica')),
    ('fuente', ('fuente',)),
    ('sistema', ('windows', 'sistema operativo', 'android', 'ios', 'formate', 'reinstal')),
    ('camara', ('camara',)),
    ('audio', ('parlante', 'microfono', 'audio', 'auricular')),
    ('puerto', ('usb', 'hdmi', 'puerto', 'jack', 'conector')),
    ('flex', ('flex', 'bisagra')),
    ('impresora', ('cabezal', 'rodillo', 'fusor', 'cartucho', 'toner')),
]
_PALABRAS_VACIAS = set('el la los las un una unos unas de del al y o que se le lo en con por para no si es '
                       'muy mas su sus me mi equipo cliente esta estaba tiene tenia fue hay ya'.split())


def normalizar(texto):
    t = unicodedata.normalize('NFD', (texto or '').lower())
    t = ''.join(ch for ch in t if unicodedata.category(ch) != 'Mn')
    return re.sub(r'\s+', ' ', t).strip()


_PATRONES = {}


def _aparece(palabra, texto):
    """Palabras cortas (≤4 letras: «red», «ram», «usb») solo como palabra
    completa; las largas también como inicio de palabra («recuper» → recuperé)."""
    rx = _PATRONES.get(palabra)
    if rx is None:
        rx = re.compile(r'\b' + re.escape(palabra) + (r'\b' if len(palabra) <= 4 else ''))
        _PATRONES[palabra] = rx
    return rx.search(texto) is not None


def _puntaje(texto, reglas, extra=None, peso_extra=2):
    """Categoría con más palabras encontradas. `extra` (el diagnóstico del
    técnico) pesa el doble que `texto` (lo que dijo el cliente)."""
    mejor, mejor_n = None, 0
    for codigo, palabras in reglas:
        n = sum(1 for p in palabras if _aparece(p, texto))
        if extra:
            n += peso_extra * sum(1 for p in palabras if _aparece(p, extra))
        if n > mejor_n:
            mejor, mejor_n = codigo, n
    return mejor


# Si la solución menciona varias cosas, manda la de más peso: un cambio de pieza
# o una reparación de board pesan más que la limpieza que se hizo de paso.
_PRIORIDAD_SOLUCION = ('sin_reparacion', 'recuperacion_datos', 'reparacion_board', 'cambio_pieza', 'mejora',
                       'desbloqueo', 'virus', 'reinstalacion', 'configuracion', 'limpieza', 'diagnostico')


def _primera(texto, reglas):
    presentes = {codigo for codigo, palabras in reglas if any(_aparece(p, texto) for p in palabras)}
    for codigo in _PRIORIDAD_SOLUCION:
        if codigo in presentes:
            return codigo
    return None


def _etiquetas(*textos, limite=6):
    vistas, salida = set(), []
    for texto in textos:
        for palabra in re.findall(r'[a-z0-9]{4,}', normalizar(texto)):
            if palabra in _PALABRAS_VACIAS or palabra.isdigit() or palabra in vistas:
                continue
            vistas.add(palabra)
            salida.append(palabra)
            if len(salida) >= limite:
                return salida
    return salida


def por_reglas(caso):
    """Clasificación sin IA. `caso`: dict con tipo, falla, diagnostico, solucion, piezas."""
    reportada = normalizar(caso.get('falla') or '')
    diagnostico = normalizar(caso.get('diagnostico') or '')
    problema = f'{reportada} {diagnostico}'.strip()
    solucion = normalizar(caso.get('solucion') or '')
    piezas = normalizar(' '.join(caso.get('piezas') or []))
    falla = _puntaje(reportada, _REGLAS_FALLA, diagnostico)
    if caso.get('tipo') == 'ups' and falla in (None, 'bateria_carga'):
        falla = 'energia'
    sol = _primera(solucion, _REGLAS_SOLUCION) if solucion else None
    if piezas and sol in (None, 'reinstalacion', 'configuracion', 'limpieza'):
        sol = 'cambio_pieza'          # si se registró una pieza cambiada, eso fue la solución
    componente = _puntaje(piezas, _REGLAS_COMPONENTE) or _puntaje(solucion, _REGLAS_COMPONENTE) \
        or _puntaje(problema, _REGLAS_COMPONENTE)
    if caso.get('tipo') == 'ups' and componente == 'bateria':
        componente = 'baterias_ups'
    if sol in ('reinstalacion', 'configuracion', 'virus') and not piezas:
        componente = 'sistema'
    resumen = ''
    if falla:
        resumen = NOMBRE_FALLA[falla]
        if sol:
            resumen += f' → {NOMBRE_SOLUCION[sol].lower()}'
            if componente and componente not in ('ninguno', 'otro', 'sistema') and sol == 'cambio_pieza':
                resumen += f' ({NOMBRE_COMPONENTE[componente].lower()})'
    return {
        'falla_categoria': falla or ('otro' if problema else None),
        'componente': componente,
        'solucion_categoria': sol,
        'etiquetas': _etiquetas(caso.get('falla'), caso.get('diagnostico'), caso.get('solucion'), *caso.get('piezas', [])),
        'resumen_caso': resumen[:400] or None,
    }


def _por_ia(caso, base):
    """Mejora la clasificación con la IA (lista cerrada). None si no hay IA o no sirve."""
    try:
        import services.ai_service as ai
        ok, _ = ai.estado_ia()
        if not ok:
            return None
    except Exception:  # noqa: BLE001
        return None
    from services import servicio_tecnico_tipos as tipos
    user = (f"Equipo: {tipos.nombre(caso.get('tipo'))} {caso.get('marca') or ''} {caso.get('modelo') or ''}\n"
            f"Falla que reportó el cliente: {caso.get('falla') or '-'}\n"
            f"Diagnóstico del técnico: {caso.get('diagnostico') or '-'}\n"
            f"Solución aplicada: {caso.get('solucion') or '-'}\n"
            f"Piezas cambiadas: {', '.join(caso.get('piezas') or []) or '-'}\n\n"
            'Clasifica el caso. Usa EXACTAMENTE uno de estos códigos en cada campo:\n'
            f"falla_categoria: {', '.join(c for c, _ in FALLAS)}\n"
            f"componente: {', '.join(c for c, _ in COMPONENTES)}\n"
            f"solucion_categoria: {', '.join(c for c, _ in SOLUCIONES)} (o null si aún no hay solución)\n"
            'Responde SOLO un JSON: {"falla_categoria": "...", "componente": "...", "solucion_categoria": "...", '
            '"etiquetas": ["máximo 6 palabras clave"], "resumen": "una frase: problema → solución"}. '
            'No inventes: si un dato no está, usa "otro" o null.')
    try:
        texto, _err = ai._chat('Eres el asistente de un taller de reparación. Respondes solo JSON válido.', user,
                               max_tokens=300, temperature=0.1, espera_frio=30, tarea='contenido')
    except Exception:  # noqa: BLE001
        return None
    from services.servicio_tecnico_ia import _json_de
    datos = _json_de(texto) if texto else None
    if not isinstance(datos, dict):
        return None
    salida = dict(base)
    if datos.get('falla_categoria') in NOMBRE_FALLA:
        salida['falla_categoria'] = datos['falla_categoria']
    if datos.get('componente') in NOMBRE_COMPONENTE:
        salida['componente'] = datos['componente']
    if datos.get('solucion_categoria') in NOMBRE_SOLUCION and caso.get('solucion'):
        salida['solucion_categoria'] = datos['solucion_categoria']
    etiquetas = [normalizar(str(e))[:30] for e in (datos.get('etiquetas') or []) if str(e).strip()]
    if etiquetas:
        salida['etiquetas'] = list(dict.fromkeys(etiquetas + base.get('etiquetas', [])))[:8]
    resumen = ' '.join(str(datos.get('resumen') or '').split())[:400]
    if resumen:
        salida['resumen_caso'] = resumen
    return salida


def caso_de_orden(orden_id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT o.id, o.falla_reportada, o.diagnostico, o.solucion, o.clasificacion_fuente,
                              e.tipo, e.marca, e.modelo
                       FROM st_ordenes o JOIN st_equipos e ON e.id = o.equipo_id WHERE o.id = %s""", (orden_id,))
        o = cur.fetchone()
        if not o:
            return None
        cur.execute('SELECT componente FROM st_cambios WHERE orden_id = %s', (orden_id,))
        piezas = [r['componente'] for r in cur.fetchall()]
    return {'id': o['id'], 'tipo': o['tipo'], 'marca': o['marca'], 'modelo': o['modelo'],
            'falla': o['falla_reportada'], 'diagnostico': o['diagnostico'], 'solucion': o['solucion'],
            'piezas': piezas, 'fuente_actual': o['clasificacion_fuente']}


def _guardar(orden_id, c, fuente):
    with get_db_cursor() as cur:
        cur.execute("""UPDATE st_ordenes SET falla_categoria = %s, componente = %s, solucion_categoria = %s,
                              etiquetas = %s, resumen_caso = %s, clasificacion_fuente = %s, clasificado_en = NOW()
                       WHERE id = %s AND COALESCE(clasificacion_fuente, '') <> 'manual'""",
                    (c.get('falla_categoria'), c.get('componente'), c.get('solucion_categoria'),
                     ', '.join(c.get('etiquetas') or [])[:300] or None, c.get('resumen_caso'), fuente, orden_id))
        return cur.rowcount > 0


def clasificar_orden(orden_id, usar_ia=True):
    """Clasifica (reglas y, si se puede, IA). Devuelve la clasificación o None."""
    caso = caso_de_orden(orden_id)
    if not caso or caso['fuente_actual'] == 'manual':
        return None
    base = por_reglas(caso)
    final, fuente = base, 'reglas'
    if usar_ia:
        ia = _por_ia(caso, base)
        if ia:
            final, fuente = ia, 'ia'
    _guardar(orden_id, final, fuente)
    return {**final, 'fuente': fuente}


def clasificar_en_segundo_plano(orden_id):
    """Reglas al instante (la página no espera) y la IA después, en un hilo."""
    caso = caso_de_orden(orden_id)
    if not caso or caso['fuente_actual'] == 'manual':
        return
    _guardar(orden_id, por_reglas(caso), 'reglas')
    app = current_app._get_current_object()

    def _con_ia():
        with app.app_context():
            try:
                clasificar_orden(orden_id, usar_ia=True)
            except Exception as exc:  # noqa: BLE001
                app.logger.warning(f'servicio_tecnico: no se pudo clasificar la orden {orden_id}: {exc}')
    _lanzar(_con_ia)


def _lanzar(fn):
    """Corre `fn` en un hilo (las pruebas lo reemplazan para correrlo ya)."""
    threading.Thread(target=fn, daemon=True).start()


def clasificar_manual(orden_id, falla, componente, solucion, usuario_id=None):
    """El técnico corrige la clasificación: queda fija ('manual')."""
    if falla not in NOMBRE_FALLA or (componente and componente not in NOMBRE_COMPONENTE) \
            or (solucion and solucion not in NOMBRE_SOLUCION):
        raise ValueError('Clasificación no válida.')
    caso = caso_de_orden(orden_id)
    if not caso:
        raise ValueError('La orden no existe.')
    base = por_reglas(caso)
    resumen = NOMBRE_FALLA[falla] + (f' → {NOMBRE_SOLUCION[solucion].lower()}' if solucion else '')
    with get_db_cursor() as cur:
        cur.execute("""UPDATE st_ordenes SET falla_categoria = %s, componente = %s, solucion_categoria = %s,
                              etiquetas = COALESCE(etiquetas, %s), resumen_caso = %s,
                              clasificacion_fuente = 'manual', clasificado_en = NOW() WHERE id = %s""",
                    (falla, componente or None, solucion or None, ', '.join(base['etiquetas']) or None,
                     resumen, orden_id))


def _hay_ia():
    try:
        import services.ai_service as ai
        return bool(ai.estado_ia()[0])
    except Exception:  # noqa: BLE001
        return False


def clasificar_pendientes(limite=30, usar_ia=True, refinar=False):
    """Clasifica las órdenes sin clasificación (historial viejo). Con
    `refinar` y la IA disponible, también repasa las que quedaron con reglas."""
    con_reglas = refinar and usar_ia and _hay_ia()
    with get_db_cursor() as cur:
        cur.execute("""SELECT id FROM st_ordenes
                       WHERE clasificacion_fuente IS NULL OR (%s AND clasificacion_fuente = 'reglas')
                       ORDER BY (clasificacion_fuente IS NULL) DESC, id DESC LIMIT %s""", (con_reglas, limite))
        ids = [r[0] for r in cur.fetchall()]
    hechas = 0
    for oid in ids:
        if clasificar_orden(oid, usar_ia=usar_ia):
            hechas += 1
    return hechas
