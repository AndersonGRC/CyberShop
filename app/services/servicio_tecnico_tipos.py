"""Tipos de equipo del Servicio Técnico y los campos propios de cada uno.

Las columnas comunes (marca, modelo, serial, sistema operativo, procesador,
RAM, almacenamiento, pantalla, color) viven en `st_equipos`. Lo que solo tiene
sentido para un tipo (ranuras de RAM de un computador, baterías de una UPS,
pulgadas de un televisor…) va en `st_equipos.extras` (JSONB) con las claves de
`CAMPOS_EXTRA`. Agregar un tipo o un campo aquí no necesita migración.

Cada campo extra: (clave, etiqueta, tipo_input, opciones).
  tipo_input = 'texto' | 'numero' | 'opcion' | 'fecha' | 'si_no'
"""

TIPOS = [
    # (código, nombre, ícono Font Awesome, columnas comunes que se muestran)
    ('computador', 'Computador de escritorio', 'desktop',
     ('marca', 'modelo', 'serial', 'sistema_operativo', 'procesador', 'ram', 'almacenamiento', 'color')),
    ('portatil', 'Portátil', 'laptop',
     ('marca', 'modelo', 'serial', 'sistema_operativo', 'procesador', 'ram', 'almacenamiento', 'pantalla', 'color')),
    ('celular', 'Celular', 'mobile-alt',
     ('marca', 'modelo', 'serial', 'imei', 'sistema_operativo', 'procesador', 'ram', 'almacenamiento', 'pantalla', 'color')),
    ('tablet', 'Tablet', 'tablet-alt',
     ('marca', 'modelo', 'serial', 'imei', 'sistema_operativo', 'procesador', 'ram', 'almacenamiento', 'pantalla', 'color')),
    ('televisor', 'Televisor', 'tv',
     ('marca', 'modelo', 'serial', 'sistema_operativo', 'pantalla', 'color')),
    ('monitor', 'Monitor', 'desktop',
     ('marca', 'modelo', 'serial', 'pantalla', 'color')),
    ('impresora', 'Impresora', 'print',
     ('marca', 'modelo', 'serial', 'color')),
    ('ups', 'UPS / regulador', 'car-battery',
     ('marca', 'modelo', 'serial', 'color')),
    ('bateria', 'Batería', 'battery-half',
     ('marca', 'modelo', 'serial')),
    ('consola', 'Consola de videojuegos', 'gamepad',
     ('marca', 'modelo', 'serial', 'almacenamiento', 'color')),
    ('red', 'Equipo de red (router, switch, cámara)', 'network-wired',
     ('marca', 'modelo', 'serial', 'color')),
    ('otro', 'Otro dispositivo', 'microchip',
     ('marca', 'modelo', 'serial', 'color')),
]

ETIQUETAS_COMUNES = {
    'marca': 'Marca',
    'modelo': 'Modelo',
    'serial': 'Serial',
    'imei': 'IMEI',
    'color': 'Color',
    'sistema_operativo': 'Sistema operativo',
    'procesador': 'Procesador',
    'ram': 'Memoria RAM',
    'almacenamiento': 'Almacenamiento',
    'pantalla': 'Pantalla',
}

_DISCO = ['HDD', 'SSD SATA', 'SSD NVMe', 'eMMC', 'Mixto (SSD + HDD)']
_PANEL = ['LED', 'LCD', 'OLED', 'QLED', 'Mini LED', 'Plasma']

CAMPOS_EXTRA = {
    'computador': [
        ('tipo_disco', 'Tipo de disco', 'opcion', _DISCO),
        ('ram_ranuras_total', 'Ranuras de RAM (total)', 'numero', None),
        ('ram_ranuras_libres', 'Ranuras de RAM libres', 'numero', None),
        ('ram_maxima', 'RAM máxima soportada', 'texto', None),
        ('tarjeta_video', 'Tarjeta de video', 'texto', None),
        ('fuente_poder', 'Fuente de poder', 'texto', None),
        ('board', 'Board / placa base', 'texto', None),
        ('licencia_windows', 'Licencia de Windows activa', 'si_no', None),
    ],
    'portatil': [
        ('tipo_disco', 'Tipo de disco', 'opcion', _DISCO),
        ('ram_ranuras_total', 'Ranuras de RAM (total)', 'numero', None),
        ('ram_ranuras_libres', 'Ranuras de RAM libres', 'numero', None),
        ('ram_maxima', 'RAM máxima soportada', 'texto', None),
        ('tarjeta_video', 'Tarjeta de video', 'texto', None),
        ('bateria_desgaste', 'Desgaste de batería (%)', 'numero', None),
        ('cargador', 'Cargador (voltaje / vatios)', 'texto', None),
        ('licencia_windows', 'Licencia de Windows activa', 'si_no', None),
    ],
    'celular': [
        ('imei2', 'IMEI 2', 'texto', None),
        ('bateria_salud', 'Salud de batería (%)', 'numero', None),
        ('version_sistema', 'Versión del sistema', 'texto', None),
        ('operador', 'Operador', 'texto', None),
        ('cuenta_vinculada', 'Cuenta (Google / iCloud) vinculada', 'si_no', None),
    ],
    'tablet': [
        ('imei2', 'IMEI 2', 'texto', None),
        ('bateria_salud', 'Salud de batería (%)', 'numero', None),
        ('version_sistema', 'Versión del sistema', 'texto', None),
        ('conectividad', 'Conectividad', 'opcion', ['Solo Wi-Fi', 'Wi-Fi + celular']),
        ('cuenta_vinculada', 'Cuenta (Google / iCloud) vinculada', 'si_no', None),
    ],
    'televisor': [
        ('pulgadas', 'Pulgadas', 'numero', None),
        ('tipo_panel', 'Tipo de panel', 'opcion', _PANEL),
        ('resolucion', 'Resolución', 'opcion', ['HD', 'Full HD', '4K', '8K']),
        ('smart', 'Smart TV', 'si_no', None),
    ],
    'monitor': [
        ('pulgadas', 'Pulgadas', 'numero', None),
        ('tipo_panel', 'Tipo de panel', 'opcion', ['IPS', 'VA', 'TN', 'OLED']),
        ('resolucion', 'Resolución', 'texto', None),
        ('entradas', 'Entradas (HDMI, DP, VGA…)', 'texto', None),
    ],
    'impresora': [
        ('tecnologia', 'Tecnología', 'opcion', ['Tinta', 'Tanque de tinta', 'Láser', 'Térmica', 'Matriz de punto']),
        ('multifuncional', 'Multifuncional', 'si_no', None),
        ('conexion', 'Conexión', 'texto', None),
        ('contador_paginas', 'Contador de páginas', 'numero', None),
    ],
    'ups': [
        ('capacidad_va', 'Capacidad (VA)', 'numero', None),
        ('capacidad_w', 'Potencia (W)', 'numero', None),
        ('topologia', 'Tipo', 'opcion', ['Interactiva', 'Online', 'Offline / standby', 'Regulador']),
        ('autonomia_min', 'Autonomía (minutos)', 'numero', None),
        ('baterias_cantidad', 'Número de baterías', 'numero', None),
        ('baterias_tipo', 'Tipo de batería', 'texto', None),
        ('baterias_voltaje', 'Voltaje / capacidad de batería', 'texto', None),
        ('baterias_ultimo_cambio', 'Último cambio de baterías', 'fecha', None),
    ],
    'bateria': [
        ('voltaje', 'Voltaje', 'texto', None),
        ('capacidad', 'Capacidad (Ah / mAh)', 'texto', None),
        ('quimica', 'Química', 'opcion', ['Plomo-ácido (VRLA)', 'Litio', 'Ni-MH', 'Otra']),
        ('uso', 'Equipo donde se usa', 'texto', None),
        ('fecha_instalacion', 'Fecha de instalación', 'fecha', None),
    ],
    'consola': [
        ('version', 'Versión / edición', 'texto', None),
        ('controles', 'Controles incluidos', 'numero', None),
    ],
    'red': [
        ('direccion_ip', 'Dirección IP', 'texto', None),
        ('firmware', 'Firmware', 'texto', None),
    ],
    'otro': [],
}

TIPO_POR_CODIGO = {t[0]: t for t in TIPOS}
CODIGOS = [t[0] for t in TIPOS]


def es_valido(codigo):
    return codigo in TIPO_POR_CODIGO


def nombre(codigo):
    t = TIPO_POR_CODIGO.get(codigo)
    return t[1] if t else 'Dispositivo'


def icono(codigo):
    t = TIPO_POR_CODIGO.get(codigo)
    return t[2] if t else 'microchip'


def columnas(codigo):
    """Columnas comunes que aplican al tipo (en orden de la ficha)."""
    t = TIPO_POR_CODIGO.get(codigo) or TIPO_POR_CODIGO['otro']
    return list(t[3])


def campos_extra(codigo):
    return CAMPOS_EXTRA.get(codigo, [])


def claves_extra(codigo):
    return [c[0] for c in campos_extra(codigo)]


def limpiar_extras(codigo, datos):
    """Solo las claves que corresponden al tipo, como texto recortado; las
    vacías no se guardan."""
    salida = {}
    for clave, _etq, tipo_input, opciones in campos_extra(codigo):
        valor = datos.get(clave)
        if valor is None:
            continue
        valor = str(valor).strip()[:200]
        if not valor:
            continue
        if tipo_input == 'si_no':
            valor = 'si' if valor.lower() in ('si', 'sí', 'true', '1', 'on', 'yes') else 'no'
        elif tipo_input == 'opcion' and opciones and valor not in opciones:
            continue
        salida[clave] = valor
    return salida


def para_plantilla():
    """Estructura que usan los formularios (JS) para mostrar los campos del tipo."""
    return {
        codigo: {
            'nombre': nom,
            'icono': ico,
            'columnas': list(cols),
            'extras': [{'clave': c[0], 'etiqueta': c[1], 'tipo': c[2], 'opciones': c[3] or []}
                       for c in CAMPOS_EXTRA.get(codigo, [])],
        }
        for codigo, nom, ico, cols in TIPOS
    }
