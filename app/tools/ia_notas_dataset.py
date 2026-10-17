"""Banco de 100 ejemplos para afinar (fine-tuning) la IA en las notas adicionales de
las cotizaciones (1.9.13.0), legales en Colombia y justas para el cliente y el negocio.

Cada ejemplo es una conversación (sistema, petición, respuesta ideal) con EXACTAMENTE
el formato que usa la app (services/ia_notas_cotizacion.py): la respuesta ideal sale
de las cláusulas revisadas de services/notas_cotizacion.py, con las indicaciones del
negocio aplicadas y, cuando pide algo abusivo, la alternativa justa y el aviso.

50 negocios × 2 variantes (empresa / persona natural, con o sin indicaciones, notas ya
escritas, pedidos abusivos). Nombres de negocios y clientes inventados.

Uso:
    python tools/ia_notas_dataset.py        # escribe tools/ia_datasets/notas_cotizacion/
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import ia_notas_cotizacion as inc  # noqa: E402
from services import notas_cotizacion as nc  # noqa: E402

SALIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ia_datasets', 'notas_cotizacion')
S, N = True, False          # con IVA / sin IVA

NEGOCIOS = [
    ('TecnoSoluciones Andina', 'Bogotá', [(2, 'Mantenimiento preventivo de portátil', S), (1, 'Cambio de pantalla de portátil 15.6"', S)]),
    ('Redes y Datos del Caribe', 'Barranquilla', [(12, 'Instalación de cableado estructurado categoría 6 (punto de red)', S), (1, 'Rack de pared 9U con organizador', S)]),
    ('Vigilancia Segura', 'Cali', [(1, 'Kit 8 cámaras de videovigilancia con NVR', S), (1, 'Instalación y configuración del sistema de cámaras', S)]),
    ('Dulce Tentación Repostería', 'Medellín', [(1, 'Torta personalizada de tres pisos para 60 personas', N), (60, 'Cupcakes decorados', N)]),
    ('Eventos Bambú', 'Bucaramanga', [(1, 'Alquiler de sonido profesional para evento', S), (80, 'Alquiler de sillas Tiffany', S), (1, 'Decoración y montaje del salón', S)]),
    ('Web Creativa', 'Pereira', [(1, 'Diseño y desarrollo de página web corporativa (5 secciones)', S), (1, 'Hosting y dominio .com por un año', S)]),
    ('Mueblería El Roble', 'Cúcuta', [(1, 'Cocina integral en madera a medida', S), (1, 'Closet en madera de 2,40 m', S)]),
    ('Pinturas y Acabados JM', 'Bogotá', [(1, 'Mano de obra pintura de apartamento de 70 m²', N), (1, 'Resane y estuco de muros', N)]),
    ('Electro Instalaciones Pacífico', 'Cali', [(1, 'Instalación eléctrica de oficina (10 tomas y 6 luminarias)', S), (1, 'Tablero eléctrico de 12 circuitos', S)]),
    ('Impresos Rápidos', 'Manizales', [(1000, 'Tarjetas de presentación impresas a full color', S), (2, 'Pendón 1 x 2 m en gran formato', S)]),
    ('Lente Mágico Estudio', 'Medellín', [(1, 'Sesión fotográfica de producto (40 fotos editadas)', S), (1, 'Video promocional de 1 minuto', S)]),
    ('Asesorías Contables Integrales', 'Bogotá', [(1, 'Asesoría contable y tributaria mensual (8 horas)', S)]),
    ('Capacitaciones Pro', 'Armenia', [(1, 'Curso de Excel avanzado para 15 personas (16 horas)', S)]),
    ('Agencia Impulso Digital', 'Bogotá', [(1, 'Gestión de redes sociales (12 publicaciones al mes)', S), (1, 'Diseño de logotipo e identidad corporativa', S)]),
    ('Mudanzas Express', 'Bogotá', [(1, 'Trasteo de apartamento de 3 habitaciones dentro de la ciudad', S)]),
    ('Limpieza Total', 'Barranquilla', [(1, 'Servicio de limpieza profunda de oficina de 200 m²', S), (1, 'Fumigación de bodega', S)]),
    ('Software Licencias', 'Bogotá', [(10, 'Licencia Microsoft 365 Empresa Estándar (1 año)', S), (10, 'Antivirus corporativo (1 año)', S)]),
    ('TecnoCel Reparaciones', 'Ibagué', [(1, 'Cambio de batería de celular Samsung A54', S), (1, 'Diagnóstico de celular que no enciende', S)]),
    ('Computadores Nuevos', 'Medellín', [(5, 'Portátil Lenovo IdeaPad 15" Core i5 nuevo', S), (5, 'Mouse inalámbrico', S)]),
    ('ReCompu Usados', 'Bogotá', [(3, 'Portátil Dell Latitude reacondicionado', S), (1, 'iPhone 12 de 128 GB usado', S)]),
    ('Catering Sabores', 'Cartagena', [(120, 'Refrigerios para evento empresarial', N), (1, 'Servicio de meseros para evento (4 meseros)', S)]),
    ('Construcciones Firmes', 'Villavicencio', [(1, 'Remodelación de baño con enchape de cerámica', S), (1, 'Impermeabilización de cubierta de 50 m²', S)]),
    ('Soporte IT Empresarial', 'Bogotá', [(1, 'Plan de mantenimiento mensual de equipos (20 computadores)', S), (1, 'Mesa de ayuda remota', S)]),
    ('Panadería La Espiga', 'Tunja', [(200, 'Panes para evento (pan francés y mantequilla)', N), (4, 'Ponqué de vainilla de 2 libras', N)]),
    ('Drone Visual', 'Santa Marta', [(1, 'Cubrimiento aéreo con drone de evento (2 horas)', S), (1, 'Edición de video del evento', S)]),
    ('Alquiler Equipos Andes', 'Bogotá', [(2, 'Alquiler de videobeam por día', S), (1, 'Alquiler de pantalla de proyección', S)]),
    ('Seguridad Electrónica del Sur', 'Pasto', [(1, 'Alarma inalámbrica con 6 sensores', S), (1, 'Control de acceso biométrico para puerta principal', S)]),
    ('Fibra y Conexión', 'Neiva', [(1, 'Tendido de fibra óptica entre dos edificios (200 m)', S), (2, 'Configuración de access point empresarial', S)]),
    ('Tienda Virtual Fácil', 'Bogotá', [(1, 'Desarrollo de tienda virtual con pasarela de pagos', S), (1, 'Capacitación para administrar la tienda (2 horas)', S)]),
    ('Carpintería Artesanal', 'Popayán', [(1, 'Puerta en madera maciza con instalación', S), (1, 'Escritorio en madera a medida', S)]),
    ('PrintFix Taller de Impresoras', 'Bogotá', [(3, 'Mantenimiento de impresora láser', S), (1, 'Cambio de rodillo de impresora', S)]),
    ('Banquetes Elegancia', 'Medellín', [(150, 'Banquete para boda (plato fuerte y postre)', N), (1, 'Menaje y mantelería para 150 personas', S)]),
    ('Gráficas del Norte', 'Barranquilla', [(5000, 'Volantes impresos media carta', S), (500, 'Sticker troquelado', S)]),
    ('Consultoría Gestión SST', 'Bogotá', [(1, 'Consultoría para diseño del sistema de gestión SST', S), (1, 'Auditoría interna', S)]),
    ('Academia de Inglés Bridge', 'Cali', [(1, 'Curso de inglés empresarial para 10 personas (40 horas)', S)]),
    ('Luz Eficiente', 'Valledupar', [(1, 'Instalación de sistema de iluminación LED para bodega', S)]),
    ('Agua Pura Tanques', 'Bogotá', [(2, 'Lavado y desinfección de tanques de agua', S)]),
    ('Jardines Verdes', 'Rionegro', [(1, 'Mantenimiento de jardines mensual', S)]),
    ('Marketing Local', 'Bogotá', [(1, 'Campaña publicitaria en redes sociales por un mes', S), (1, 'Pauta en Instagram y Facebook', S)]),
    ('App Móvil Studio', 'Medellín', [(1, 'Desarrollo de aplicación móvil para pedidos (Android y iOS)', S)]),
    ('Servicio Técnico Hogar', 'Bucaramanga', [(1, 'Reparación de nevera que no enfría', S), (1, 'Mantenimiento de lavadora', S)]),
    ('Hogar Seguro Cámaras', 'Bogotá', [(1, 'Kit 4 cámaras de videovigilancia con DVR', S)]),
    ('Tecnología Gamer', 'Bogotá', [(1, 'Tarjeta de video RTX 4060 nueva', S), (1, 'Fuente de poder 650 W', S)]),
    ('Fiesta Feliz Decoraciones', 'Cali', [(1, 'Decoración de fiesta infantil con globos', S), (1, 'Animación infantil (2 horas)', S)]),
    ('Fotografía Eventos Luz', 'Bogotá', [(1, 'Cubrimiento fotográfico de matrimonio (8 horas)', S), (1, 'Álbum impreso de 30 páginas', S)]),
    ('Transportes Rápidos', 'Medellín', [(1, 'Transporte de mercancía Medellín - Bogotá (1 tonelada)', S)]),
    ('Asesoría Empresarial Pyme', 'Bogotá', [(1, 'Asesoría para constitución de empresa (S.A.S.)', S)]),
    ('Hosting Colombia', 'Bogotá', [(1, 'Hosting empresarial por un año', S), (5, 'Correo corporativo (1 año)', S)]),
    ('WiFi Hogar', 'Medellín', [(1, 'Instalación de red WiFi en malla para casa', S), (3, 'Access point en malla con configuración', S)]),
    ('Pastelería Fina', 'Bogotá', [(2, 'Caja de galletas artesanales', N), (1, 'Postre de tres leches familiar', N)]),
]

EMPRESAS = [('Comercializadora Delta S.A.S.', '901.234.567-1'), ('Inversiones Montaña S.A.S.', '900.765.432-5'),
            ('Distribuidora El Faro Ltda.', '800.123.987-3'), ('Grupo Horizonte S.A.S.', '901.555.210-8')]
PERSONAS = [('Laura Gómez', '1.032.456.789'), ('Andrés Rojas', '79.845.123'), ('Camila Torres', '1.144.987.321'),
            ('Juan Pablo Díaz', '1.020.333.444')]

# Indicaciones del negocio: valores (anticipo, días, garantía) y algunos pedidos abusivos,
# para que el modelo aprenda a aplicarlos y a negarse con la alternativa justa.
INDICACIONES = ['', 'anticipo del 50 %', 'anticipo del 60 %, entrega en 8 días', 'vigencia de 30 días',
                'garantía de 6 meses', 'pon que no hay garantía', 'entrega en 15 días y anticipo del 40 %',
                'el anticipo no es reembolsable',
                'el valor incluye los materiales básicos; los materiales adicionales se informan al cliente y se cobran aparte',
                'no se aceptan devoluciones', 'vigencia de 10 días, anticipo del 30 %',
                'no nos hacemos responsables por daños', 'entrega en 5 días', '', 'garantía de 1 año',
                # Condiciones propias del negocio: deben quedar como notas, bien redactadas.
                'el transporte fuera del perímetro urbano se cobra aparte',
                'anticipo del 50 %. Los trabajos en domingo o festivo tienen un recargo del 20 %',
                'indica que incluye una visita de seguimiento sin costo durante el primer mes',
                'el anticipo no es reembolsable y el transporte se cobra aparte',
                'agrega que los precios no incluyen el desplazamiento fuera de la ciudad']
# Notas que el negocio ya tiene: el modelo las analiza, no las repite y solo complementa;
# si alguna es abusiva, lo advierte.
NOTAS_PREVIAS = ['', '', 'Precios con IVA incluido.', '',
                 'VIGENCIA Y PRECIOS\n• Esta cotización es válida por 15 días calendario desde su fecha; durante ese '
                 'plazo se mantienen los precios y condiciones ofrecidos (arts. 845 y 846 del Código de Comercio).', '',
                 'FORMA DE PAGO\n• 50 % de anticipo y el saldo contra entrega.\n\nGARANTÍA\n'
                 '• Garantía de 3 meses sobre el trabajo realizado.',
                 'CONDICIONES\n• No se aceptan devoluciones.']


def escenarios():
    salida = []
    for i, (negocio, ciudad, items) in enumerate(NEGOCIOS):
        for variante in (0, 1):
            k = i * 2 + variante
            empresa = (i + variante) % 2 == 0
            nombre, documento = (EMPRESAS if empresa else PERSONAS)[k % 4]
            salida.append({
                'negocio': negocio,
                'cliente': {'nombre': nombre, 'documento': documento, 'ciudad': ciudad},
                'items': [{'cantidad': c, 'descripcion': d, 'iva': 19 if iva else 0} for c, d, iva in items],
                'indicaciones': INDICACIONES[k % len(INDICACIONES)],
                'notas_actuales': NOTAS_PREVIAS[k % len(NOTAS_PREVIAS)],
            })
    return salida


def ejemplo(e):
    ctx = nc.contexto(e['items'], e['cliente'], e['indicaciones'])
    base = nc.sugerencias_base(e['items'], e['cliente'], e['indicaciones'], e['notas_actuales'])
    respuesta = {'secciones': base['secciones'], 'avisos': base['avisos']}     # el formato que pide la app
    return {'messages': [
        {'role': 'system', 'content': inc.SISTEMA.format(negocio=e['negocio'])},
        {'role': 'user', 'content': inc.peticion(ctx, e['notas_actuales'], (e['cliente']['nombre'],))},
        {'role': 'assistant', 'content': json.dumps(respuesta, ensure_ascii=False)},
    ]}, ctx


def main():
    os.makedirs(SALIDA, exist_ok=True)
    lista = escenarios()
    banco = []
    with open(os.path.join(SALIDA, 'notas_cotizacion_ft.jsonl'), 'w', encoding='utf-8', newline='\n') as f:
        for e in lista:
            fila, ctx = ejemplo(e)
            f.write(json.dumps(fila, ensure_ascii=False) + '\n')
            banco.append({**e, 'categorias_esperadas': ctx['categorias'], 'cliente_tipo': ctx['cliente'],
                          'pide_algo_abusivo': bool(ctx['avisos'] or nc.revisar_notas(e['notas_actuales'])),
                          'condiciones_esperadas': [t for _, t in ctx['condiciones']]})
    with open(os.path.join(SALIDA, 'banco_notas_cotizacion.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(banco, f, ensure_ascii=False, indent=1)
    print(f'{len(lista)} ejemplos → {SALIDA}')
    sin_categoria = [e['items'][0]['descripcion'] for e in banco if not e['categorias_esperadas']]
    print('Sin categoría (venta general):', len(sin_categoria), sin_categoria[:6])
    print('Con pedido abusivo:', sum(e['pide_algo_abusivo'] for e in banco))
    print('Con condiciones propias del negocio:', sum(bool(e['condiciones_esperadas']) for e in banco))


if __name__ == '__main__':
    main()
