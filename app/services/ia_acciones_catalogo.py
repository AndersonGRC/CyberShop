"""Acciones del panel sobre el catálogo: productos, movimientos de inventario y
categorías (fase 2 del CRUD de la IA).

El motor (services/ia_acciones.py) sigue siendo el único que interpreta,
autoriza, guarda la propuesta y confirma. Aquí solo está lo propio del
catálogo: armar la vista previa (preparar) y escribir al confirmar (ejecutar),
con consultas fijas en la BD del cliente activo.

Reglas:
  - Nunca se borra: archivar = active FALSE (y oculto en la tienda), como
    routes/admin.py:938-991. Sin la columna `active`, no se archiva desde la IA.
  - La referencia no se cambia: es la llave con que el escritorio sincroniza.
  - El stock solo cambia con ajustar_inventario (valor final) o
    movimiento_inventario (entrada/salida) y siempre deja rastro en inventario_log.
  - Renombrar una categoría «toca» sus productos para que su trigger mueva
    updated_at y el escritorio refresque el nombre de la categoría.
  - Al confirmar se compara con la vista previa (snapshot); si algo cambió,
    se pide una propuesta nueva.
"""
import re
import uuid
from decimal import Decimal, InvalidOperation

from services.ia import buscador
from services.ia_acciones import AccionAclarar, AccionError, _entero, _texto

PRODUCTO_EDITABLES = ('nombre', 'precio', 'costo', 'descripcion', 'categoria', 'stock_minimo')
PRODUCTO_CREACION = ('nombre', 'precio', 'categoria', 'referencia', 'descripcion', 'costo', 'stock')
# El stock NO va en el snapshot: una venta entre la vista previa y la
# confirmación no invalida un cambio de precio. Los movimientos de inventario
# sí comparan el stock (ver _ejecutar_movimiento).
_SNAPSHOT = ('id', 'nombre', 'precio', 'costo', 'descripcion', 'genero_id', 'stock_minimo',
             'active')


def _columnas(cur):
    cur.execute("SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'productos'")
    return {r['column_name'] for r in cur.fetchall()}


def _existe(cur, tabla):
    cur.execute('SELECT to_regclass(%s) AS t', (f'public.{tabla}',))
    fila = cur.fetchone()
    return bool(fila and fila['t'])


def _plano(valor):
    """Para comparar snapshots: Decimal/float/str → texto canónico."""
    if valor is None:
        return None
    if isinstance(valor, (Decimal, float, int)) and not isinstance(valor, bool):
        return format(Decimal(str(valor)).normalize(), 'f')
    return valor


def _monto(valor, nombre, minimo=Decimal('0'), estricto=False):
    """Precio o costo: número ≥ 0 (> 0 si `estricto`). Acepta 3500, "3.500", "$3.500,50"."""
    if isinstance(valor, bool) or valor is None:
        raise AccionAclarar(f'¿Cuál es el {nombre}?')
    if isinstance(valor, (int, float)):
        texto = repr(valor)
    else:
        # En pesos colombianos «3.500» es tres mil quinientos y «3.500,50» lleva decimales.
        s = str(valor).strip().lstrip('$').strip().replace(' ', '')
        if re.fullmatch(r'\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+,\d{1,2}', s):
            texto = s.replace('.', '').replace(',', '.')
        elif re.fullmatch(r'\d+(?:\.\d{1,2})?', s):
            texto = s
        elif re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?', s):
            texto = s.replace(',', '')
        else:
            raise AccionAclarar(f'¿Cuál es el {nombre} exacto? Escríbelo como 3500 o 3.500.')
    try:
        numero = Decimal(texto)
    except (InvalidOperation, ValueError):
        raise AccionAclarar(f'¿Cuál es el {nombre}? Escríbelo como un número.')
    if numero < minimo or (estricto and numero <= 0) or numero > Decimal('1000000000'):
        raise AccionAclarar(f'El {nombre} debe ser un número mayor que cero.')
    return numero.quantize(Decimal('0.01'))


def _pesos(numero):
    from helpers import formatear_moneda
    return formatear_moneda(float(numero))


# ── Buscar el registro ─────────────────────────────────────────
def producto(cur, plan, bloquear=False, activo=True):
    """El producto de la orden, por ID o buscado por parecido. Con varios
    candidatos muestra las opciones con su ID; no adivina."""
    columnas = _columnas(cur)
    tiene_active = 'active' in columnas
    estado = '' if not tiene_active else (' activo' if activo else ' archivado')
    extra = [c for c in ('costo', 'stock_minimo', 'active') if c in columnas]
    select = ('SELECT id, nombre, referencia, precio, stock, genero_id, descripcion'
              + ''.join(f', {c}' for c in extra) + ' FROM productos WHERE id = %s')
    if plan.get('producto_id') is not None:
        pid = _entero(plan['producto_id'], 'el ID del producto')
        cur.execute(select + (' FOR UPDATE' if bloquear else ''), (pid,))
        filas = cur.fetchall()
        if len(filas) != 1 or (tiene_active and bool(filas[0]['active']) != activo):
            raise AccionAclarar(f'No encontré un producto{estado} con el ID {pid}. '
                                '¿Cuál es su nombre o su referencia?')
        return dict(filas[0])
    referencia = _texto(plan.get('producto'), 'producto', 200, obligatorio=True)
    filas, modo = buscador.productos(cur, referencia, activos=activo, tiene_active=tiene_active)
    elegido = buscador.elegir(filas, modo)
    if elegido is None:
        if not filas:
            raise AccionAclarar(f'No encontré un producto{estado} como «{referencia}». '
                                '¿Cuál es su nombre, referencia o ID?')
        lineas = buscador.opciones(filas, extra=lambda f: f.get('referencia'))
        raise AccionAclarar('Encontré varios productos: ' + '; '.join(lineas)
                            + '. ¿Cuál es? Responde con su ID.')
    cur.execute(select, (elegido['id'],))
    return dict(cur.fetchone())


def categoria(cur, referencia):
    """La categoría por ID («ID 3»), nombre exacto o parecido."""
    if isinstance(referencia, int) and not isinstance(referencia, bool):
        cur.execute('SELECT id, nombre FROM generos WHERE id = %s', (referencia,))
        fila = cur.fetchone()
        if fila:
            return dict(fila)
        raise AccionAclarar(f'No encontré la categoría con el ID {referencia}. ¿Cuál es su nombre?')
    nombre = _texto(referencia, 'categoría', 100, obligatorio=True)
    filas, modo = buscador.categorias(cur, nombre)
    elegido = buscador.elegir(filas, modo)
    if elegido is not None:
        return {'id': elegido['id'], 'nombre': elegido['nombre']}
    if filas:
        raise AccionAclarar('Encontré varias categorías: ' + '; '.join(buscador.opciones(filas))
                            + '. ¿Cuál es? Responde con su ID.')
    cur.execute('SELECT nombre FROM generos ORDER BY nombre LIMIT 12')
    existentes = ', '.join(r['nombre'] for r in cur.fetchall()) or '(ninguna)'
    raise AccionAclarar(f'No encontré la categoría «{nombre}». Las que hay son: {existentes}. '
                        '¿En cuál va? Si es nueva, pídeme primero «crea la categoría …».')


def _nombre_libre(cur, nombre, excluir=None):
    sql = 'SELECT id FROM productos WHERE LOWER(nombre) = LOWER(%s)'
    params = [nombre]
    if 'active' in _columnas(cur):
        sql += ' AND COALESCE(active, TRUE)'
    if excluir is not None:
        sql += ' AND id <> %s'
        params.append(excluir)
    cur.execute(sql + ' LIMIT 1', params)
    fila = cur.fetchone()
    if fila:
        raise AccionError(f'Ya existe un producto «{nombre}» (ID {fila["id"]}). '
                          'Usa otro nombre o edita ese producto.')


def _referencia_libre(cur, referencia):
    cur.execute('SELECT id FROM productos WHERE LOWER(referencia) = LOWER(%s) LIMIT 1', (referencia,))
    fila = cur.fetchone()
    if fila:
        raise AccionError(f'La referencia «{referencia}» ya la usa el producto ID {fila["id"]}.')


def _referencia_nueva(cur):
    for _ in range(5):
        ref = 'IA-' + uuid.uuid4().hex[:8].upper()
        cur.execute('SELECT 1 FROM productos WHERE referencia = %s', (ref,))
        if not cur.fetchone():
            return ref
    raise AccionError('No pude generar una referencia única. Indica una referencia.')


def _categoria_libre(cur, nombre, excluir=None):
    sql = 'SELECT id FROM generos WHERE LOWER(nombre) = LOWER(%s)'
    params = [nombre]
    if excluir is not None:
        sql += ' AND id <> %s'
        params.append(excluir)
    cur.execute(sql + ' LIMIT 1', params)
    fila = cur.fetchone()
    if fila:
        raise AccionError(f'Ya existe la categoría «{nombre}» (ID {fila["id"]}).')


def _snapshot(fila):
    return {k: _plano(fila.get(k)) for k in _SNAPSHOT if k in fila}


def _sin_cambios_desde(fila, snapshot, que='El producto'):
    actual = _snapshot(fila)
    if any(actual.get(k) != v for k, v in (snapshot or {}).items()):
        raise AccionError(f'{que} cambió desde la vista previa. Prepara una nueva propuesta.')


# ── Vista previa ───────────────────────────────────────────────
def preparar(cur, plan):
    tipo = plan['tipo']
    return _PREPARAR[tipo](cur, plan)


def _preparar_crear_producto(cur, plan):
    campos = plan.get('campos')
    if not isinstance(campos, dict):
        raise AccionAclarar('¿Cuál es el nombre del producto?')
    if set(campos) - set(PRODUCTO_CREACION):
        raise AccionError('La solicitud incluye campos de producto no permitidos.')
    columnas = _columnas(cur)
    nombre = _texto(campos.get('nombre'), 'nombre del producto', 200, obligatorio=True)
    precio = _monto(campos.get('precio'), 'precio de venta', estricto=True)
    if campos.get('categoria') in (None, ''):
        raise AccionAclarar(f'¿En qué categoría va «{nombre}»?')
    cat = categoria(cur, campos['categoria'])
    referencia = _texto(campos.get('referencia'), 'referencia', 60)
    descripcion = _texto(campos.get('descripcion'), 'descripción', 2000)
    costo = None
    if campos.get('costo') not in (None, ''):
        if 'costo' not in columnas:
            raise AccionError('Esta tienda no guarda el costo de los productos.')
        costo = _monto(campos['costo'], 'costo')
    stock = 0
    if campos.get('stock') not in (None, ''):
        stock = _entero(campos['stock'], 'el stock inicial', minimo=0)
    _nombre_libre(cur, nombre)
    if referencia:
        _referencia_libre(cur, referencia)
    payload = {'tipo': 'crear_producto', 'campos': {
        'nombre': nombre, 'precio': str(precio), 'genero_id': cat['id'], 'categoria': cat['nombre'],
        'referencia': referencia, 'descripcion': descripcion,
        'costo': str(costo) if costo is not None else None, 'stock': stock}}
    detalles = [f'Nombre: {nombre}', f'Precio: {_pesos(precio)}',
                f"Categoría: {cat['nombre']} (ID {cat['id']})",
                f'Referencia: {referencia or "se genera automáticamente (IA-…)"}']
    if descripcion:
        detalles.append(f'Descripción: {descripcion}')
    if costo is not None:
        detalles.append(f'Costo: {_pesos(costo)}')
    detalles.append(f'Stock inicial: {stock}')
    detalles.append('Sin foto: la puedes subir después en el panel de productos.')
    return payload, f'Crear producto {nombre} a {_pesos(precio)}.', detalles


def _preparar_editar_producto(cur, plan):
    cambios = plan.get('cambios')
    if not isinstance(cambios, dict) or not cambios:
        raise AccionAclarar('¿Qué dato del producto deseas cambiar y cuál es el valor nuevo?')
    if 'referencia' in cambios:
        raise AccionError('La referencia no se cambia desde la IA: es la llave con que el '
                          'escritorio reconoce el producto. Cámbiala en el panel si es necesario.')
    if 'stock' in cambios:
        raise AccionAclarar('El stock se cambia con un movimiento: «fija el stock de … en 20» o '
                            '«entraron 10 …». ¿Cuál quieres hacer?')
    if set(cambios) - set(PRODUCTO_EDITABLES):
        raise AccionError('La solicitud incluye campos de producto no permitidos.')
    columnas = _columnas(cur)
    actual = producto(cur, plan)
    nuevos, detalles = {}, [f"Producto: {actual['nombre']} (ID {actual['id']}, referencia {actual['referencia']})"]
    for campo, valor in cambios.items():
        if campo in ('costo', 'stock_minimo') and campo not in columnas:
            raise AccionError(f'Esta tienda no guarda «{campo}» en los productos.')
        if campo == 'nombre':
            nuevo = _texto(valor, 'nombre del producto', 200, obligatorio=True)
            if nuevo.lower() != (actual['nombre'] or '').lower():
                _nombre_libre(cur, nuevo, excluir=actual['id'])
            nuevos['nombre'] = nuevo
            detalles.append(f"Nombre: {actual['nombre']} → {nuevo}")
        elif campo in ('precio', 'costo'):
            nuevo = _monto(valor, 'precio de venta' if campo == 'precio' else 'costo',
                           estricto=campo == 'precio')
            nuevos[campo] = nuevo
            anterior = actual.get(campo)
            detalles.append(f"{campo.capitalize()}: {_pesos(anterior or 0)} → {_pesos(nuevo)}")
        elif campo == 'descripcion':
            nuevo = _texto(valor, 'descripción', 2000)
            nuevos['descripcion'] = nuevo
            detalles.append('Descripción: ' + (nuevo or '(vacía)'))
        elif campo == 'categoria':
            cat = categoria(cur, valor)
            nuevos['genero_id'] = cat['id']
            detalles.append(f"Categoría → {cat['nombre']} (ID {cat['id']})")
        elif campo == 'stock_minimo':
            nuevos['stock_minimo'] = _entero(valor, 'el stock mínimo', minimo=0)
            detalles.append(f"Stock mínimo: {actual.get('stock_minimo')} → {nuevos['stock_minimo']}")
    nuevos = {k: v for k, v in nuevos.items() if _plano(v) != _plano(actual.get(k))}
    if not nuevos:
        raise AccionError('Los datos indicados ya son los actuales; no hay cambios.')
    payload = {'tipo': 'editar_producto', 'producto_id': actual['id'],
               'snapshot': _snapshot(actual),
               'cambios': {k: str(v) if isinstance(v, Decimal) else v for k, v in nuevos.items()}}
    return payload, f"Editar producto {actual['nombre']} (ID {actual['id']}).", detalles


def _preparar_estado_producto(cur, plan):
    tipo = plan['tipo']
    if 'active' not in _columnas(cur):
        raise AccionError('Esta tienda no permite archivar productos desde la IA; '
                          'hazlo desde el panel de productos.')
    archivar = tipo == 'archivar_producto'
    # Se archiva uno activo; se reactiva uno archivado.
    actual = producto(cur, plan, activo=archivar)
    payload = {'tipo': tipo, 'producto_id': actual['id'], 'snapshot': _snapshot(actual)}
    detalles = [f"Producto: {actual['nombre']} (ID {actual['id']}, referencia {actual['referencia']})",
                f"Precio: {_pesos(actual['precio'] or 0)}", f"Stock: {actual['stock'] or 0}"]
    if archivar:
        detalles.append('Se archiva: deja de verse en la tienda y en las listas, pero no se '
                        'borra; sus ventas y su historial se conservan.')
        return payload, f"Archivar producto {actual['nombre']} (ID {actual['id']}).", detalles
    detalles.append('Vuelve a estar visible en la tienda y en las listas.')
    return payload, f"Reactivar producto {actual['nombre']} (ID {actual['id']}).", detalles


def _preparar_movimiento(cur, plan):
    direccion = plan.get('direccion')
    if direccion not in ('entrada', 'salida'):
        raise AccionAclarar('¿Es una entrada (llegó mercancía) o una salida (daño, merma, uso)?')
    cantidad = _entero(plan.get('cantidad'), 'la cantidad', minimo=1, maximo=1_000_000)
    motivo = _texto(plan.get('motivo'), 'motivo', 500) or (
        'Entrada de mercancía' if direccion == 'entrada' else 'Salida de inventario')
    actual = producto(cur, plan)
    anterior = int(actual['stock'] or 0)
    nuevo = anterior + cantidad if direccion == 'entrada' else anterior - cantidad
    if nuevo < 0:
        raise AccionError(f"{actual['nombre']} tiene {anterior} unidades: no alcanzan para una "
                          f'salida de {cantidad}. Revisa la cantidad o fija el stock real.')
    payload = {'tipo': 'movimiento_inventario', 'producto_id': actual['id'],
               'stock_anterior': anterior, 'stock_nuevo': nuevo, 'nombre': actual['nombre'],
               'referencia': actual['referencia'], 'motivo': motivo}
    signo = '+' if direccion == 'entrada' else '−'
    detalles = [f"Producto: {actual['nombre']} (ID {actual['id']}, referencia {actual['referencia']})",
                f'Movimiento: {direccion} de {cantidad} ({signo}{cantidad})',
                f'Stock: {anterior} → {nuevo}', f'Motivo: {motivo}']
    return payload, (f"Registrar {direccion} de {cantidad} unidades de {actual['nombre']} "
                     f'({anterior} → {nuevo}).'), detalles


def _preparar_crear_categoria(cur, plan):
    nombre = _texto(plan.get('nombre'), 'nombre de la categoría', 50, obligatorio=True)
    _categoria_libre(cur, nombre)
    return ({'tipo': 'crear_categoria', 'nombre': nombre}, f'Crear la categoría {nombre}.',
            [f'Nombre: {nombre}', 'Queda vacía hasta que le asignes productos.'])


def _preparar_renombrar_categoria(cur, plan):
    cat = categoria(cur, plan.get('categoria_id') if plan.get('categoria_id') is not None
                    else plan.get('categoria'))
    nuevo = _texto(plan.get('nombre_nuevo'), 'nuevo nombre de la categoría', 50, obligatorio=True)
    if nuevo == cat['nombre']:
        raise AccionError('Ese ya es el nombre de la categoría.')
    _categoria_libre(cur, nuevo, excluir=cat['id'])
    cur.execute('SELECT COUNT(*) AS n FROM productos WHERE genero_id = %s', (cat['id'],))
    n = int(cur.fetchone()['n'])
    return ({'tipo': 'renombrar_categoria', 'categoria_id': cat['id'], 'nombre_anterior': cat['nombre'],
             'nombre_nuevo': nuevo},
            f"Renombrar la categoría {cat['nombre']} a {nuevo}.",
            [f"Categoría: {cat['nombre']} (ID {cat['id']})", f'Nombre nuevo: {nuevo}',
             f'Productos que la usan: {n} (se actualizan también en el escritorio).'])


_PREPARAR = {
    'crear_producto': _preparar_crear_producto,
    'editar_producto': _preparar_editar_producto,
    'archivar_producto': _preparar_estado_producto,
    'reactivar_producto': _preparar_estado_producto,
    'movimiento_inventario': _preparar_movimiento,
    'crear_categoria': _preparar_crear_categoria,
    'renombrar_categoria': _preparar_renombrar_categoria,
}
TIPOS = tuple(_PREPARAR)


# ── Escritura al confirmar ─────────────────────────────────────
def ejecutar(cur, fila, usuario):
    return _EJECUTAR[fila['tipo']](cur, fila['payload'], usuario)


def _log(cur, producto_id, anterior, nuevo, motivo, usuario):
    if not _existe(cur, 'inventario_log'):
        return
    delta = nuevo - anterior
    cur.execute("""INSERT INTO inventario_log
                   (producto_id, tipo, cantidad, stock_anterior, stock_nuevo, motivo, usuario_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (producto_id, 'ENTRADA' if delta > 0 else 'SALIDA', delta, anterior, nuevo,
                 f'IA confirmada: {motivo}', usuario))


def _ejecutar_crear_producto(cur, payload, usuario):
    c = payload['campos']
    columnas = _columnas(cur)
    cur.execute('LOCK TABLE productos IN SHARE ROW EXCLUSIVE MODE')
    _nombre_libre(cur, c['nombre'])
    referencia = c.get('referencia')
    if referencia:
        _referencia_libre(cur, referencia)
    else:
        referencia = _referencia_nueva(cur)
    cur.execute('SELECT id FROM generos WHERE id = %s', (c['genero_id'],))
    if not cur.fetchone():
        raise AccionError('La categoría ya no existe. Prepara una nueva propuesta.')
    valores = {'imagen': '', 'nombre': c['nombre'], 'precio': Decimal(c['precio']),
               'referencia': referencia, 'genero_id': c['genero_id'],
               'descripcion': c.get('descripcion') or '', 'stock': int(c.get('stock') or 0)}
    if c.get('costo') is not None and 'costo' in columnas:
        valores['costo'] = Decimal(c['costo'])
    if 'visible_en_ecommerce' in columnas:
        valores['visible_en_ecommerce'] = True
    nombres = ', '.join(valores)
    marcas = ', '.join(['%s'] * len(valores))
    cur.execute(f'INSERT INTO productos ({nombres}) VALUES ({marcas}) RETURNING id',
                tuple(valores.values()))
    pid = int(cur.fetchone()['id'])
    if valores['stock'] > 0:
        _log(cur, pid, 0, valores['stock'], 'stock inicial del producto creado', usuario)
    return {'mensaje': f"Producto {c['nombre']} creado (ID {pid}, referencia {referencia}).",
            'producto_id': pid}


def _ejecutar_editar_producto(cur, payload, usuario):
    actual = producto(cur, {'producto_id': payload['producto_id']}, bloquear=True)
    _sin_cambios_desde(actual, payload.get('snapshot'))
    cambios = payload['cambios']
    if 'nombre' in cambios:
        _nombre_libre(cur, cambios['nombre'], excluir=actual['id'])
    valores = {k: (Decimal(v) if k in ('precio', 'costo') else v) for k, v in cambios.items()}
    asignaciones = ', '.join(f'{k} = %s' for k in valores)
    cur.execute(f'UPDATE productos SET {asignaciones} WHERE id = %s',
                (*valores.values(), actual['id']))
    return {'mensaje': f"Producto {actual['nombre']} actualizado (ID {actual['id']}).",
            'producto_id': actual['id']}


def _ejecutar_estado_producto(cur, payload, usuario):
    archivar = payload['tipo'] == 'archivar_producto'
    actual = producto(cur, {'producto_id': payload['producto_id']}, bloquear=True,
                      activo=archivar)
    _sin_cambios_desde(actual, payload.get('snapshot'))
    sets = ['active = %s']
    valores = [not archivar]
    if 'visible_en_ecommerce' in _columnas(cur):
        sets.append('visible_en_ecommerce = %s')
        valores.append(not archivar)
    cur.execute(f'UPDATE productos SET {", ".join(sets)} WHERE id = %s', (*valores, actual['id']))
    verbo = 'archivado' if archivar else 'reactivado'
    return {'mensaje': f"Producto {actual['nombre']} {verbo} (ID {actual['id']}).",
            'producto_id': actual['id']}


def _ejecutar_movimiento(cur, payload, usuario):
    actual = producto(cur, {'producto_id': payload['producto_id']}, bloquear=True)
    anterior = int(actual['stock'] or 0)
    if (anterior != payload['stock_anterior'] or actual['nombre'] != payload['nombre']
            or actual['referencia'] != payload['referencia']):
        raise AccionError('El producto cambió desde la vista previa. Prepara una nueva propuesta.')
    nuevo = _entero(payload['stock_nuevo'], 'el stock final', minimo=0)
    cur.execute('UPDATE productos SET stock = %s WHERE id = %s', (nuevo, actual['id']))
    _log(cur, actual['id'], anterior, nuevo, payload['motivo'], usuario)
    return {'mensaje': f"Stock de {actual['nombre']}: {anterior} → {nuevo}.",
            'producto_id': actual['id'], 'stock_nuevo': nuevo}


def _ejecutar_crear_categoria(cur, payload, usuario):
    cur.execute('LOCK TABLE generos IN SHARE ROW EXCLUSIVE MODE')
    _categoria_libre(cur, payload['nombre'])
    cur.execute('INSERT INTO generos (nombre) VALUES (%s) RETURNING id', (payload['nombre'],))
    gid = int(cur.fetchone()['id'])
    return {'mensaje': f"Categoría {payload['nombre']} creada (ID {gid}).", 'categoria_id': gid}


def _ejecutar_renombrar_categoria(cur, payload, usuario):
    cur.execute('SELECT id, nombre FROM generos WHERE id = %s FOR UPDATE', (payload['categoria_id'],))
    fila = cur.fetchone()
    if not fila or fila['nombre'] != payload['nombre_anterior']:
        raise AccionError('La categoría cambió desde la vista previa. Prepara una nueva propuesta.')
    _categoria_libre(cur, payload['nombre_nuevo'], excluir=fila['id'])
    cur.execute('UPDATE generos SET nombre = %s WHERE id = %s', (payload['nombre_nuevo'], fila['id']))
    # El escritorio guarda el nombre de la categoría en cada producto y sincroniza
    # por updated_at: «tocar» sus productos hace que su trigger la mueva.
    cur.execute('UPDATE productos SET nombre = nombre WHERE genero_id = %s', (fila['id'],))
    return {'mensaje': f"Categoría {payload['nombre_anterior']} renombrada a "
                       f"{payload['nombre_nuevo']} (ID {fila['id']}).", 'categoria_id': fila['id']}


_EJECUTAR = {
    'crear_producto': _ejecutar_crear_producto,
    'editar_producto': _ejecutar_editar_producto,
    'archivar_producto': _ejecutar_estado_producto,
    'reactivar_producto': _ejecutar_estado_producto,
    'movimiento_inventario': _ejecutar_movimiento,
    'crear_categoria': _ejecutar_crear_categoria,
    'renombrar_categoria': _ejecutar_renombrar_categoria,
}
