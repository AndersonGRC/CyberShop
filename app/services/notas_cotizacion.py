# -*- coding: utf-8 -*-
"""Notas adicionales de las cotizaciones: catálogo de cláusulas revisadas (1.9.13.0).

Cláusulas cortas, legales en Colombia y justas para el cliente y para el negocio,
agrupadas por sección y por tipo de lo que se cotiza. Sirven para tres cosas:
  1. Son la REFERENCIA que recibe la IA (services/ia_notas_cotizacion.py): escoge y
     adapta las que aplican, sin inventar normas.
  2. Son las sugerencias base cuando la IA no responde.
  3. Generan el banco de ejemplos para afinar el modelo (tools/ia_datasets/).

Normas que se citan (solo estas): Ley 1480 de 2011 (Estatuto del Consumidor),
Ley 1581 de 2012 (datos personales), Código de Comercio (oferta e intereses),
Estatuto Tributario (IVA), Ley 23 de 1982 y Ley 1450 de 2011 (derechos de autor),
Resolución 2674 de 2013 (alimentos), Resolución 4272 de 2021 (trabajo en alturas)
y el RETIE. Los valores que el negocio debe confirmar van entre [corchetes].

Este módulo no habla con la IA ni con la base de datos: solo datos y texto.
"""
import re
import unicodedata

# Orden en que salen las secciones en la cotización.
SECCIONES = ('Vigencia y precios', 'Alcance del servicio', 'Tiempos de entrega', 'Forma de pago',
             'Garantía', 'Responsabilidades del cliente', 'Propiedad intelectual', 'Cancelaciones',
             'Impuestos y facturación', 'Datos personales')
MAX_SECCIONES = 8
MAX_NOTAS_SECCION = 4
MAX_NOTAS = 20                  # en total: la cotización no se vuelve un contrato de diez páginas
MAX_LARGO_NOTA = 280
# Al recortar se conservan primero estas (y antes que todas, las propias del servicio).
PRIORIDAD = ('Vigencia y precios', 'Alcance del servicio', 'Forma de pago', 'Garantía', 'Tiempos de entrega',
             'Propiedad intelectual', 'Cancelaciones', 'Responsabilidades del cliente', 'Impuestos y facturación',
             'Datos personales')
# Sin derecho de retracto por ley (art. 47 de la Ley 1480 de 2011): perecederos, hechos a la
# medida y programas informáticos abiertos.
_SIN_RETRACTO = {'alimentos', 'muebles', 'impresion', 'software'}

# Normas que se pueden citar. Una nota que cite otra se descarta (la IA no inventa leyes).
NORMAS_PERMITIDAS = ('ley 1480 de 2011', 'ley 1581 de 2012', 'codigo de comercio', 'estatuto tributario',
                     'ley 23 de 1982', 'ley 1450 de 2011', 'resolucion 2674 de 2013',
                     'resolucion 4272 de 2021', 'retie')

# Frases de cláusulas abusivas (art. 43 de la Ley 1480 de 2011): nunca en una nota.
_ABUSIVAS = (r'sin garantia', r'no (tiene|hay|aplica|cuenta con) garantia', r'no se (aceptan|hacen|admiten) (cambios|devoluciones|reclamos)',
             r'no (es|son) reembolsable', r'no se devuelve(n)? (el|los|ningun)', r'bajo ninguna circunstancia',
             r'renuncia(r)? a (su|sus|cualquier)', r'no nos hacemos responsables', r'no (se )?responde(mos)? por ning',
             r'sin derecho a reclam', r'perdera(n)? (el|todo)')


def normalizar(texto):
    """Minúsculas y sin tildes (para comparar)."""
    t = unicodedata.normalize('NFKD', str(texto or '').lower())
    return ''.join(ch for ch in t if not unicodedata.combining(ch))


def es_abusiva(nota):
    n = normalizar(nota)
    return any(re.search(p, n) for p in _ABUSIVAS)


_CITA = re.compile(r'\b(ley|decreto|resolucion|circular|acuerdo)\s+(n[o°º.]*\s*)?\d[\d.]*(\s+de\s+\d{4})?')


def cita_norma_no_permitida(nota):
    """¿La nota cita una ley, decreto o resolución fuera de la lista revisada?"""
    n = normalizar(nota)
    for m in _CITA.finditer(n):
        cita = re.sub(r'\s+', ' ', m.group(0)).replace('no. ', '').replace('n° ', '')
        if not any(cita.startswith(p) or p.startswith(cita) for p in NORMAS_PERMITIDAS):
            return True
    return False


# ── Cláusulas ──────────────────────────────────────────────────────────────────
# (sección, texto). {vigencia}, {anticipo}, {entrega}, {garantia}: valores que se
# llenan con las indicaciones del negocio o quedan entre corchetes para confirmar.

COMUNES = {
    'vigencia': ('Vigencia y precios', 'Esta cotización es válida por {vigencia} días calendario desde su fecha; '
                 'durante ese plazo se mantienen los precios y condiciones ofrecidos (arts. 845 y 846 del Código de Comercio).'),
    'moneda': ('Vigencia y precios', 'Los valores están en pesos colombianos (COP). Cualquier trabajo o producto '
               'adicional se cotiza por aparte y se aprueba antes de ejecutarlo.'),
    'iva_incluido': ('Impuestos y facturación', 'Los valores incluyen el IVA del 19 % en los productos y servicios '
                     'gravados, discriminado en el total (Estatuto Tributario).'),
    'iva_no': ('Impuestos y facturación', 'Los valores no incluyen IVA. [Si el negocio no es responsable de IVA, '
               'indícalo aquí; si lo es, agrega el 19 % a lo que esté gravado.]'),
    'factura': ('Impuestos y facturación', 'Al aprobar la cotización se expide la factura de venta correspondiente.'),
    'retenciones': ('Impuestos y facturación', 'Si el cliente es agente de retención, aplica las retenciones de ley '
                    'sobre el valor antes de IVA y entrega el certificado correspondiente.'),
    'pago_anticipo': ('Forma de pago', 'Forma de pago: {anticipo} % de anticipo para iniciar y el saldo contra '
                      'entrega a satisfacción.'),
    'pago_contado': ('Forma de pago', 'Forma de pago: el valor total al confirmar el pedido o contra entrega '
                     '[ajusta según tu negocio].'),
    'medios_pago': ('Forma de pago', 'Medios de pago: transferencia bancaria o efectivo [agrega tus medios]; el pago '
                    'se entiende hecho cuando el dinero está disponible en la cuenta del negocio.'),
    'mora': ('Forma de pago', 'Los saldos vencidos pueden causar intereses de mora dentro del límite legal '
             '(art. 884 del Código de Comercio).'),
    'cambios_alcance': ('Alcance del servicio', 'Cualquier cambio en el alcance se acuerda por escrito antes de '
                        'ejecutarlo y puede modificar el valor y el plazo.'),
    'cancelacion_justa': ('Cancelaciones', 'Si el cliente cancela después de aprobar la cotización, del anticipo solo '
                          'se descuentan los costos ya causados (materiales comprados o trabajo hecho), con sus '
                          'soportes, y se devuelve el saldo.'),
    'retracto': ('Cancelaciones', 'Si la compra se hace a distancia (internet, teléfono o catálogo), el cliente puede '
                 'retractarse dentro de los 5 días hábiles siguientes a la entrega, salvo las excepciones de ley '
                 '(art. 47 de la Ley 1480 de 2011).'),
    'datos': ('Datos personales', 'Los datos del cliente se usan solo para gestionar esta cotización, el servicio y su '
              'facturación (Ley 1581 de 2012); puede consultarlos, corregirlos o pedir que se eliminen.'),
    'garantia_servicio': ('Garantía', 'El servicio tiene la garantía legal de calidad de la Ley 1480 de 2011: si no se '
                          'presta en las condiciones acordadas, se vuelve a prestar sin costo o se devuelve lo pagado '
                          'por esa parte.'),
}

CATEGORIAS = {
    'reparacion': {
        'nombre': 'servicio técnico y reparación de equipos',
        'palabras': ('diagnostico', 'formate', 'cambio de pantalla', 'cambio de bateria', 'revision tecnica',
                     'soporte tecnico', 'servicio tecnico', 'instalacion de windows', 'limpieza interna',
                     'recuperacion de datos', 'cambio de disco', 'repotenciacion'),
        'debiles': ('mantenimiento', 'reparacion', 'reparar', 'revision', 'limpieza'),
        'requiere': ('computador', 'portatil', 'laptop', 'pc', 'impresora', 'celular', 'telefono', 'tablet',
                     'equipo', 'servidor', 'televisor', 'consola', 'monitor', 'ups', 'escaner', 'videobeam',
                     'proyector', 'aire acondicionado', 'nevera', 'lavadora'),
        'servicio': True,
        'clausulas': [
            ('Alcance del servicio', 'El diagnóstico tiene un valor de [$ valor] que se descuenta del total si el '
                                     'cliente aprueba la reparación.'),
            ('Alcance del servicio', 'Los repuestos solo se instalan con la aprobación del cliente; los que se cambien '
                                     'se le entregan si los solicita.'),
            ('Garantía', 'Garantía de la reparación: {garantia} sobre el trabajo hecho y los repuestos instalados, '
                         'contados desde la entrega del equipo.'),
            ('Garantía', 'La garantía no cubre daños por golpes, humedad, variaciones de voltaje o manipulación de '
                         'terceros no autorizados (art. 16 de la Ley 1480 de 2011).'),
            ('Responsabilidades del cliente', 'Recomendamos respaldar la información antes del servicio; se tomarán las '
                                              'precauciones razonables para conservarla y la recuperación de datos no '
                                              'está incluida salvo que se indique.'),
            ('Responsabilidades del cliente', 'Si el equipo no se retira dentro del mes siguiente a la fecha de entrega '
                                              'acordada, se avisará al cliente; si no lo retira, se aplica lo previsto en '
                                              'el art. 18 de la Ley 1480 de 2011.'),
            ('Tiempos de entrega', 'Entrega estimada: {entrega} días hábiles desde la aprobación; si un repuesto se '
                                   'demora, se avisa con la nueva fecha.'),
        ],
        'garantia': '[3 meses]', 'entrega': '[3]',
    },
    'usados': {
        'nombre': 'productos usados o reacondicionados',
        'palabras': ('usado', 'usada', 'reacondicionad', 'segunda mano', 'refurbished', 'open box'),
        'servicio': False,
        'clausulas': [
            ('Garantía', 'Los productos usados o reacondicionados tienen la garantía informada aquí: {garantia} sobre su '
                         'funcionamiento (Ley 1480 de 2011); su estado se informa al cliente antes de la compra.'),
            ('Garantía', 'La garantía no cubre el desgaste propio del uso informado ni daños por golpes, humedad o mal uso.'),
        ],
        'garantia': '[3 meses]',
    },
    'software': {
        'nombre': 'licencias de software y suscripciones',
        'palabras': ('licencia', 'suscripcion', 'antivirus', 'office', 'microsoft 365', 'hosting', 'dominio',
                     'almacenamiento en la nube', 'correo corporativo'),
        'servicio': True,
        'clausulas': [
            ('Alcance del servicio', 'Las licencias se entregan a nombre del cliente y se rigen por los términos del '
                                     'fabricante; incluyen instalación y activación en [N] equipos.'),
            ('Alcance del servicio', 'Las licencias y servicios de renovación periódica (mensual o anual) se avisan '
                                     'antes de su vencimiento; la renovación no es automática sin aprobación del cliente.'),
            ('Cancelaciones', 'Las suscripciones pueden cancelarse avisando con [30] días de anticipación a la siguiente '
                              'renovación.'),
            ('Propiedad intelectual', 'Solo se instalan programas con licencia legal (Ley 23 de 1982).'),
        ],
    },
    'desarrollo': {
        'nombre': 'desarrollo web y software a la medida',
        'palabras': ('pagina web', 'sitio web', 'tienda virtual', 'tienda online', 'ecommerce', 'e-commerce',
                     'landing', 'aplicacion movil', 'app movil', 'desarrollo', 'software a la medida',
                     'plataforma web', 'pagina de internet'),
        'servicio': True,
        'clausulas': [
            ('Alcance del servicio', 'Incluye [2] rondas de ajustes sobre el diseño aprobado; ajustes o funciones '
                                     'adicionales se cotizan por aparte.'),
            ('Alcance del servicio', 'El dominio y el hosting [se incluyen el primer año]; su renovación anual corre por '
                                     'cuenta del cliente y se avisa con anticipación.'),
            ('Tiempos de entrega', 'Plazo estimado: {entrega} días hábiles desde el anticipo y la entrega completa de '
                                   'los contenidos por parte del cliente.'),
            ('Responsabilidades del cliente', 'El cliente entrega los textos, imágenes y logos, y garantiza que tiene '
                                              'derecho a usarlos.'),
            ('Garantía', 'Garantía de {garantia} para corregir sin costo errores del desarrollo entregado; no incluye '
                         'cambios de alcance ni fallas de terceros (hosting, complementos o cambios hechos por otros).'),
            ('Propiedad intelectual', 'Pagado el valor total, los derechos patrimoniales sobre el desarrollo a la medida '
                                      'pasan al cliente (art. 20 de la Ley 23 de 1982, modificado por la Ley 1450 de '
                                      '2011); las licencias de terceros siguen sus propios términos.'),
            ('Datos personales', 'Si el sitio recoge datos personales, el cliente es responsable de su tratamiento y debe '
                                 'publicar su política de datos (Ley 1581 de 2012).'),
        ],
        'garantia': '[3 meses]', 'entrega': '[30]',
    },
    'red': {
        'nombre': 'redes y cableado estructurado',
        'palabras': ('cableado estructurado', 'punto de red', 'puntos de red', 'fibra optica', 'red lan',
                     'red wifi', 'certificacion de puntos', 'cableado de red'),
        'debiles': ('switch', 'rack', 'access point', 'patch'),
        'requiere': ('instalacion', 'configuracion', 'montaje', 'cableado', 'punto'),
        'servicio': True,
        'clausulas': [
            ('Alcance del servicio', 'Incluye suministro e instalación de los puntos descritos, marquillado y pruebas '
                                     'de conectividad de cada punto.'),
            ('Alcance del servicio', 'No incluye obras civiles (regatas, perforaciones especiales, cielo raso) ni '
                                     'canalizaciones adicionales, salvo que se indique.'),
            ('Alcance del servicio', 'El personal que trabaja en alturas cuenta con certificación vigente (Resolución '
                                     '4272 de 2021).'),
            ('Responsabilidades del cliente', 'El cliente garantiza el acceso al lugar en el horario acordado y la '
                                              'energía necesaria para los equipos.'),
            ('Garantía', 'Garantía de {garantia} sobre la instalación y los materiales; los equipos activos tienen la '
                         'garantía del fabricante (Ley 1480 de 2011).'),
            ('Tiempos de entrega', 'Ejecución estimada: {entrega} días hábiles desde el anticipo y la disponibilidad '
                                   'del sitio.'),
        ],
        'garantia': '[1 año]', 'entrega': '[5]',
    },
    'cctv': {
        'nombre': 'cámaras de seguridad y videovigilancia',
        'palabras': ('camara', 'cctv', 'dvr', 'nvr', 'videovigilancia', 'vigilancia', 'alarma', 'control de acceso'),
        'servicio': True,
        'clausulas': [
            ('Alcance del servicio', 'Incluye instalación, configuración, vista remota en el celular y una explicación '
                                     'del uso del sistema al finalizar.', 'servicio'),
            ('Alcance del servicio', 'La vista remota depende de la conexión a internet del cliente; los usuarios y '
                                     'contraseñas quedan a nombre del cliente.'),
            ('Alcance del servicio', 'La grabación se guarda aproximadamente [15] días, según la cantidad de cámaras y '
                                     'la resolución.'),
            ('Garantía', 'Los equipos tienen la garantía del fabricante o, si no la indica, un (1) año (Ley 1480 de '
                         '2011); la instalación tiene {garantia}.'),
            ('Datos personales', 'Las cámaras captan imágenes de personas: el cliente debe poner avisos visibles de '
                                 'videovigilancia y usar las grabaciones solo para seguridad (Ley 1581 de 2012).'),
        ],
        'garantia': '[6 meses]', 'entrega': '[3]',
    },
    'electrico': {
        'nombre': 'instalaciones eléctricas',
        'palabras': ('instalacion electrica', 'tablero electrico', 'tomacorriente', 'tomas electricas', 'iluminacion',
                     'cableado electrico', 'acometida', 'breaker', 'electrico'),
        'servicio': True,
        'clausulas': [
            ('Alcance del servicio', 'Las instalaciones se ejecutan conforme al RETIE (Reglamento Técnico de '
                                     'Instalaciones Eléctricas).'),
            ('Responsabilidades del cliente', 'Puede ser necesario suspender la energía durante los trabajos; el horario '
                                              'se coordina con el cliente.'),
            ('Garantía', 'Garantía de {garantia} sobre la mano de obra y los materiales suministrados (Ley 1480 de 2011).'),
        ],
        'garantia': '[1 año]',
    },
    'obra': {
        'nombre': 'obras y remodelaciones',
        'palabras': ('remodelacion', 'obra civil', 'obra blanca', 'obra gris', 'pintura de', 'estuco', 'drywall',
                     'enchape', 'ceramica', 'construccion', 'mamposteria', 'demolicion', 'impermeabilizacion',
                     'cubierta', 'resane', 'adecuacion locativa'),
        'servicio': True,
        'clausulas': [
            ('Alcance del servicio', 'La cotización [incluye / no incluye] los materiales; los cambios de referencia '
                                     'pedidos por el cliente pueden modificar el valor.'),
            ('Alcance del servicio', 'Incluye la limpieza general y el retiro de escombros al finalizar.'),
            ('Tiempos de entrega', 'Plazo estimado: {entrega} días hábiles desde el anticipo; puede ampliarse por clima, '
                                   'cambios pedidos por el cliente o materiales a su cargo, lo que se informa por escrito.'),
            ('Responsabilidades del cliente', 'Los permisos de la copropiedad o de la autoridad que se requieran están a '
                                              'cargo del cliente, salvo que se indique otra cosa.'),
            ('Garantía', 'Los trabajos sobre el inmueble tienen la garantía legal de la Ley 1480 de 2011; los acabados, '
                         '{garantia} desde la entrega.'),
        ],
        'garantia': '[1 año]', 'entrega': '[10]',
    },
    'alimentos': {
        'nombre': 'alimentos y catering',
        'palabras': ('torta', 'ponque', 'pastel', 'catering', 'refrigerio', 'pasabocas', 'desayuno', 'almuerzo',
                     'comida', 'banquete', 'buffet', 'postre', 'cupcake', 'galleta', 'pan ', 'panes', 'brunch', 'cena'),
        'servicio': False,
        'clausulas': [
            ('Alcance del servicio', 'Los alimentos se elaboran bajo las condiciones sanitarias de la Resolución 2674 '
                                     'de 2013 y se preparan para la fecha acordada.'),
            ('Responsabilidades del cliente', 'El cliente informa las alergias o restricciones alimentarias antes de '
                                              'confirmar el pedido.'),
            ('Garantía', 'Por ser productos perecederos, su calidad se garantiza hasta la fecha de consumo indicada; se '
                         'recomienda refrigerarlos y consumirlos dentro de las [24] horas siguientes a la entrega.'),
            ('Cancelaciones', 'La cantidad final se confirma [3] días antes; si el pedido se cancela con menos de [48] '
                              'horas, solo se cobran los insumos ya comprados, con sus soportes.'),
        ],
    },
    'eventos': {
        'nombre': 'eventos y montajes',
        'palabras': ('evento', 'sonido', 'decoracion', 'montaje', 'carpa', 'tarima', 'dj', 'animacion', 'menaje',
                     'sillas', 'mantel'),
        'servicio': True,
        'clausulas': [
            ('Alcance del servicio', 'Incluye montaje y desmontaje en el lugar del evento en el horario acordado.'),
            ('Responsabilidades del cliente', 'El cliente garantiza el acceso al lugar y los permisos del sitio o de la '
                                              'copropiedad que se requieran.'),
            ('Cancelaciones', 'El evento puede reprogramarse una vez sin costo avisando con [8] días de anticipación; si '
                              'se cancela, solo se descuentan los costos ya causados, con sus soportes.'),
        ],
    },
    'alquiler': {
        'nombre': 'alquiler de equipos o elementos',
        'palabras': ('alquiler', 'arriendo', 'renta de', 'rentar'),
        'servicio': True,
        'clausulas': [
            ('Forma de pago', 'Se solicita un depósito de [$ valor] que se devuelve al recibir los elementos en el mismo '
                              'estado, salvo el desgaste normal por el uso.'),
            ('Responsabilidades del cliente', 'Los daños o pérdidas durante el alquiler se cobran según el costo de '
                                              'reparación o reposición, con sus soportes.'),
            ('Tiempos de entrega', 'Los elementos se entregan y recogen en las fechas acordadas; la devolución tardía '
                                   'puede generar [un día] adicional de alquiler.'),
        ],
    },
    'transporte': {
        'nombre': 'transporte y envíos',
        'palabras': ('transporte', 'envio', 'flete', 'trasteo', 'mudanza', 'mensajeria', 'acarreo'),
        'servicio': True,
        'clausulas': [
            ('Alcance del servicio', 'Incluye cargue y descargue en [primer piso]; el seguro de la mercancía [se incluye '
                                     '/ se cotiza aparte].'),
            ('Tiempos de entrega', 'Los tiempos son estimados y pueden variar por cierres viales o clima; cualquier '
                                   'novedad se informa de inmediato.'),
        ],
    },
    'consultoria': {
        'nombre': 'asesoría, consultoría y capacitación',
        'palabras': ('asesoria', 'consultoria', 'auditoria', 'acompanamiento', 'capacitacion', 'curso', 'taller',
                     'clase', 'formacion', 'entrenamiento', 'mentoria'),
        'servicio': True,
        'clausulas': [
            ('Alcance del servicio', 'Incluye [N] horas; las horas adicionales se cobran a [$ valor] cada una, con '
                                     'aprobación previa del cliente.'),
            ('Alcance del servicio', 'La asesoría se presta con diligencia profesional; los resultados dependen también '
                                     'de la información y las decisiones del cliente (art. 7 de la Ley 1480 de 2011).'),
            ('Cancelaciones', 'Las sesiones pueden reprogramarse sin costo avisando con [24] horas de anticipación.'),
            ('Datos personales', 'La información que comparta el cliente se trata como confidencial y solo se usa para '
                                 'prestar el servicio.'),
            ('Propiedad intelectual', 'El material entregado es para uso del cliente y de sus participantes; no puede '
                                      'revenderse.'),
        ],
    },
    'diseno': {
        'nombre': 'diseño gráfico y marketing',
        'palabras': ('diseno grafico', 'diseno de logo', 'logotipo', 'identidad corporativa', 'branding',
                     'publicidad', 'redes sociales', 'community', 'pauta', 'campana publicitaria',
                     'campana de marketing', 'campana en redes', 'marketing', 'piezas graficas', 'manual de marca'),
        'servicio': True,
        'clausulas': [
            ('Alcance del servicio', 'Incluye [2] rondas de ajustes; cambios adicionales o nuevas piezas se cotizan '
                                     'aparte.'),
            ('Alcance del servicio', 'El presupuesto de anuncios (pauta) no está incluido y se paga directamente a la '
                                     'plataforma; los resultados de una campaña no pueden garantizarse.'),
            ('Responsabilidades del cliente', 'El cliente garantiza que tiene derecho a usar las fotos, logos y textos '
                                              'que entrega.'),
            ('Propiedad intelectual', 'Pagado el valor total, los derechos patrimoniales sobre los diseños a la medida '
                                      'pasan al cliente (art. 20 de la Ley 23 de 1982, modificado por la Ley 1450 de '
                                      '2011); los archivos editables [se incluyen / se cotizan aparte].'),
        ],
    },
    'impresion': {
        'nombre': 'impresión y litografía',
        'palabras': ('impresion', 'impreso', 'tarjetas de presentacion', 'tarjetas personales', 'volantes', 'pendon',
                     'litografia', 'sticker', 'etiquetas adhesivas', 'gran formato', 'vinilo', 'afiche', 'brochure',
                     'talonario', 'plegable'),
        'servicio': False,
        'clausulas': [
            ('Responsabilidades del cliente', 'La producción inicia con el arte aprobado por escrito por el cliente; '
                                              'corregir errores contenidos en el arte aprobado tiene un nuevo costo.'),
            ('Alcance del servicio', 'Pueden existir pequeñas variaciones de color entre la pantalla y el impreso, '
                                     'propias del proceso.'),
            ('Forma de pago', 'Si por el proceso se entrega una cantidad distinta, se cobra la cantidad realmente '
                              'entregada.'),
            ('Garantía', 'Si el impreso tiene defectos de producción frente al arte aprobado, se repone sin costo '
                         '(Ley 1480 de 2011).'),
        ],
    },
    'foto': {
        'nombre': 'fotografía y video',
        'palabras': ('fotografia', 'fotos', 'sesion fotografica', 'filmacion', 'drone', 'cubrimiento',
                     'video promocional', 'video institucional', 'video corporativo', 'edicion de video',
                     'produccion de video', 'videoclip'),
        'servicio': True,
        'clausulas': [
            ('Tiempos de entrega', 'Se entregan [N] fotografías o videos editados en formato digital en {entrega} días '
                                   'hábiles.'),
            ('Propiedad intelectual', 'El autor conserva sus derechos morales y el cliente recibe licencia de uso del '
                                      'material para los fines acordados (Ley 23 de 1982).'),
            ('Responsabilidades del cliente', 'Si en el material aparecen personas, el cliente obtiene su autorización '
                                              'para usar su imagen (Ley 1581 de 2012).'),
        ],
        'entrega': '[8]',
    },
    'muebles': {
        'nombre': 'muebles y fabricación a la medida',
        'palabras': ('mueble', 'carpinteria', 'cocina integral', 'closet', 'puerta en madera',
                     'escritorio en madera', 'mesa en madera', 'fabricacion de muebles'),
        'servicio': False,
        'clausulas': [
            ('Alcance del servicio', 'La fabricación inicia con el diseño y las medidas aprobados por escrito por el '
                                     'cliente; incluye transporte e instalación en [la ciudad].'),
            ('Tiempos de entrega', 'Entrega estimada: {entrega} días hábiles desde el anticipo y la aprobación del diseño.'),
            ('Garantía', 'Garantía de {garantia} por defectos de fabricación (Ley 1480 de 2011); no cubre daños por '
                         'humedad, sobrepeso o mal uso.'),
            ('Cancelaciones', 'Por ser un producto hecho a la medida del cliente, no aplica el derecho de retracto '
                              '(art. 47 de la Ley 1480 de 2011).'),
        ],
        'garantia': '[1 año]', 'entrega': '[15]',
    },
    'aseo': {
        'nombre': 'aseo, limpieza y fumigación',
        'palabras': ('aseo', 'fumigacion', 'desinfeccion', 'lavado de tanques', 'jardin', 'control de plagas',
                     'limpieza de oficina', 'limpieza general', 'limpieza profunda', 'servicio de limpieza',
                     'limpieza de vidrios', 'limpieza de fachada'),
        'servicio': True,
        'clausulas': [
            ('Alcance del servicio', 'Los productos usados tienen los registros exigidos por la autoridad sanitaria y '
                                     'se aplican según su ficha técnica; se informan los tiempos de reingreso al lugar.'),
            ('Alcance del servicio', 'Los insumos [están incluidos / los aporta el cliente] y el servicio se presta en el '
                                     'horario acordado.'),
            ('Garantía', 'Si el resultado no corresponde a lo acordado, se repite el servicio sin costo dentro de '
                         '{garantia} (Ley 1480 de 2011).'),
        ],
        'garantia': '[15 días]',
    },
    'plan': {
        'nombre': 'planes y contratos de mantenimiento',
        'palabras': ('plan de mantenimiento', 'contrato de mantenimiento', 'mantenimiento mensual', 'soporte mensual',
                     'mesa de ayuda', 'iguala', 'bolsa de horas', 'mantenimiento programado'),
        'servicio': True,
        'clausulas': [
            ('Alcance del servicio', 'El plan incluye [1] visita preventiva [mensual]; las correctivas y los repuestos '
                                     'se cotizan aparte.'),
            ('Cancelaciones', 'El plan dura [12] meses y puede cancelarse avisando con [30] días de anticipación, '
                              'pagando solo lo causado.'),
        ],
    },
}

# Bienes nuevos (lo que no es servicio ni de una categoría con garantía propia).
BIENES = [
    ('Garantía', 'Los productos nuevos tienen la garantía legal de la Ley 1480 de 2011 por el término que indique el '
                 'fabricante; si no lo indica, es de un (1) año desde la entrega.'),
    ('Garantía', 'La garantía no cubre daños por mal uso, golpes, humedad o variaciones de voltaje (art. 16 de la Ley '
                 '1480 de 2011); si la falla se repite, el cliente puede pedir el cambio o la devolución del dinero.'),
    ('Tiempos de entrega', 'Entrega: {entrega} días hábiles después de confirmado el pago, sujeta a disponibilidad '
                           'de inventario.'),
]
_SIN_GARANTIA_GENERICA = {'usados', 'alimentos', 'impresion', 'muebles', 'software', 'desarrollo', 'diseno', 'foto'}

_PALABRAS_SERVICIO = ('instalacion', 'mantenimiento', 'reparacion', 'servicio', 'desarrollo', 'diseno', 'asesoria',
                      'consultoria', 'capacitacion', 'curso', 'transporte', 'envio', 'montaje', 'configuracion',
                      'soporte', 'alquiler', 'limpieza', 'aseo', 'fumigacion', 'fotografia', 'sesion', 'mano de obra',
                      'visita', 'hora', 'plan ', 'suscripcion', 'hosting', 'cubrimiento', 'cableado', 'instalac',
                      'adecuacion', 'remodelacion', 'pintura de', 'reparar', 'cambio de ', 'diagnostic', 'revision',
                      'impermeabiliz', 'auditoria', 'gestion de', 'lavado', 'desinfeccion', 'trasteo', 'mudanza',
                      'animacion', 'edicion de', 'campana de', 'campana publicitaria', 'pauta', 'tendido',
                      'decoracion', 'mesero', 'mesa de ayuda', 'resane', 'clases', 'taller de')


def _contiene(texto_n, palabras):
    return any(re.search(r'\b' + re.escape(p.strip()) + (r'\b' if p.endswith(' ') else ''), texto_n) for p in palabras)


def categorias_de(items):
    """Categorías de lo que se cotiza, en orden de aparición (sin repetir)."""
    salida = []
    for item in items or []:
        t = normalizar(item.get('descripcion'))
        if 'cableado' in t and 'electric' in t:
            claves = ['electrico']
        else:
            claves = [c for c, d in CATEGORIAS.items()
                  if _contiene(t, d['palabras']) or (_contiene(t, d.get('debiles', ()))
                                                     and _contiene(t, d.get('requiere', ())))]
            if 'red' in claves and 'electrico' in claves:
                claves.remove('electrico')
            if 'plan' in claves and 'reparacion' in claves:
                claves.remove('reparacion')
        for c in claves:
            if c not in salida:
                salida.append(c)
    return salida


def es_servicio(descripcion):
    return _contiene(normalizar(descripcion), _PALABRAS_SERVICIO)


def tipo_cliente(nombre='', documento=''):
    """'empresa' (NIT o razón social) o 'persona natural'."""
    n = normalizar(nombre)
    if re.search(r'\b(s\.?a\.?s|s\.?a|ltda|e\.?u|s\.?c\.?a|cooperativa|fundacion|corporacion|asociacion|'
                 r'empresa|grupo|inversiones|comercializadora|distribuidora)\b', n):
        return 'empresa'
    digitos = re.sub(r'\D', '', str(documento or ''))
    if '-' in str(documento or '') and len(digitos) in (9, 10) and digitos[0] in '89':
        return 'empresa'                                  # NIT con dígito de verificación
    return 'persona natural'


# ── Indicaciones del negocio («anticipo del 60 %», «sin garantía»…) ────────────
_PEDIDOS_ABUSIVOS = {
    r'sin garantia|no (tiene|hay|dar|damos|doy) garantia|quita(r)? la garantia':
        'No incluí «sin garantía»: la garantía legal no se puede quitar ni limitar (art. 43 de la Ley 1480 de 2011). '
        'Dejé claro qué no cubre (mal uso, golpes, humedad), que es lo justo para el negocio.',
    r'anticipo no (es )?(se )?(reembols|devuelv)|no (se )?devuelve el anticipo|anticipo no reembolsable':
        'No incluí que el anticipo nunca se devuelve: sería una cláusula abusiva. Dejé que, si el cliente cancela, '
        'se descuentan los costos ya causados con soportes, lo que protege al negocio sin perjudicar al cliente.',
    r'no (se )?acepta(n|mos)? (devoluciones|cambios|reclamos)|sin devoluciones':
        'No incluí «no se aceptan devoluciones»: el cliente conserva la garantía legal y, en ventas a distancia, el '
        'retracto. Dejé las condiciones de la garantía y sus exclusiones legítimas.',
    r'no (nos )?(hacemos|hago) responsables?|no respond(emos|o) por':
        'No incluí una exención total de responsabilidad: la ley no la permite (art. 43 de la Ley 1480 de 2011). '
        'Dejé las precauciones que debe tomar el cliente y lo que de verdad no cubre el servicio.',
}


def leer_indicaciones(texto):
    """Valores pedidos por el negocio y avisos si pidió algo que la ley no permite."""
    n = normalizar(texto)
    valores, avisos = {}, []
    m = re.search(r'anticipo (?:del? )?(\d{1,3}) ?%|(\d{1,3}) ?% (?:de )?anticipo', n)
    if m:
        valores['anticipo'] = m.group(1) or m.group(2)
    m = re.search(r'(?:vigencia|valida|valido|vale)\D{0,20}?(\d{1,3}) ?dias', n)
    if m:
        valores['vigencia'] = m.group(1)
    m = re.search(r'(?:entrega|plazo|tiempo de entrega|se entrega|ejecucion)\D{0,20}?(\d{1,3}) ?dias', n)
    if m:
        valores['entrega'] = m.group(1)
    m = re.search(r'garantia (?:de |por )?(\d{1,2}) ?(mes(?:es)?|ano|anos|dias)', n)
    if m:
        unidad = {'mes': 'mes', 'meses': 'meses', 'ano': 'año', 'anos': 'años', 'dias': 'días'}[m.group(2)]
        valores['garantia'] = f"{m.group(1)} {'mes' if unidad == 'meses' and m.group(1) == '1' else unidad}"
    for patron, aviso in _PEDIDOS_ABUSIVOS.items():
        if re.search(patron, n):
            avisos.append(aviso)
    return valores, avisos


# ── Condiciones propias del negocio («el valor incluye…», «el transporte va aparte») ──
# Lo que el negocio escribe en «Indicaciones» y no es un valor (anticipo, días, garantía),
# ni un pedido abusivo, ni una orden de estilo, es una condición suya: va como nota en su
# sección, siempre (con IA o sin ella).
_VALORES = (r'(?:con |un |el )?anticipo (?:del? )?\d{1,3} ?%|\d{1,3} ?% (?:de )?anticipo',
            r'(?:con |una )?(?:vigencia|valida|valido|vale)\D{0,20}?\d{1,3} ?dias(?: habiles| calendario)?',
            r'(?:con )?(?:entrega|plazo|tiempo de entrega|se entrega|ejecucion)\D{0,20}?\d{1,3} ?dias'
            r'(?: habiles| calendario)?',
            r'(?:con )?garantia (?:de |por )?\d{1,2} ?(?:mes(?:es)?|ano|anos|dias)')
_ORDEN_AL_ASISTENTE = re.compile(
    r'^(?:por favor,?\s+)?(?:indica|indique|indicar|pon|ponga|poner|coloca|coloque|agrega|agregue|agregar|anota|'
    r'anote|aclara|aclare|menciona|mencione|di|deja|escribe|escriba|especifica|especifique|recuerda|recuerde)'
    r'\s+(?:en las notas\s+|tambien\s+)?(?:que\s+)?')
_ORDEN_DE_ESTILO = re.compile(r'^(?:hazl[oa]s?|haz|usa|redacta|resume|resumelo|que sean?|en tono|mas |menos |'
                              r'solo |sin |no repitas|cortas?|formal)\b')
_TILDES = {'aqui': 'aquí', 'alli': 'allí', 'sera': 'será', 'seran': 'serán', 'estara': 'estará', 'demas': 'demás',
           'tambien': 'también', 'ademas': 'además', 'despues': 'después', 'dias': 'días', 'habiles': 'hábiles',
           'garantia': 'garantía', 'basico': 'básico', 'basicos': 'básicos', 'basica': 'básica', 'basicas': 'básicas',
           'electrico': 'eléctrico', 'electricos': 'eléctricos', 'electrica': 'eléctrica', 'electricas': 'eléctricas',
           'tecnico': 'técnico', 'tecnicos': 'técnicos', 'credito': 'crédito', 'energia': 'energía',
           'informara': 'informará', 'cobrara': 'cobrará', 'cobraran': 'cobrarán', 'incluira': 'incluirá',
           'tendra': 'tendrá', 'tendran': 'tendrán', 'podra': 'podrá', 'debera': 'deberá', 'deberan': 'deberán',
           'facturara': 'facturará', 'mas': 'más', 'perimetro': 'perímetro', 'telefono': 'teléfono'}
_SECCION_DE = ((r'\bgarantia', 'Garantía'),
               (r'\b(anticipo|abono|pago|pagos|cuotas?|transferencia|efectivo|credito|contado)\b', 'Forma de pago'),
               (r'\b(cancel|reprogram|retracto)', 'Cancelaciones'),
               (r'\b(iva|factura|facturacion|impuestos?|retencion(es)?)\b', 'Impuestos y facturación'),
               (r'\b(derechos|propiedad|autor|codigo fuente)\b', 'Propiedad intelectual'),
               (r'\b(datos personales|privacidad)\b', 'Datos personales'),
               (r'\b(material|incluye|incluido|incluidos|adicional|alcance|aparte|recargo|transporte|'
                r'desplazamiento|visita)', 'Alcance del servicio'),
               (r'\b(entrega|plazo|habiles|tiempo)', 'Tiempos de entrega'),
               (r'\b(cliente debe|cliente se compromete|responsab|acceso|permiso)', 'Responsabilidades del cliente'),
               (r'\b(vigencia|valida|precio)', 'Vigencia y precios'))


def _quitar(texto, patrones):
    """Quita del texto (con tildes) lo que los patrones encuentran en su versión normalizada."""
    n = normalizar(texto)
    if len(n) != len(texto):
        return texto
    for patron in patrones:
        for m in reversed(list(re.finditer(patron, n))):
            texto, n = texto[:m.start()] + texto[m.end():], n[:m.start()] + n[m.end():]
    return texto


def redactar_condicion(texto):
    """La condición como nota: sin «indica que…», con tildes frecuentes, mayúscula y punto."""
    t = ' '.join(str(texto or '').split())
    n = normalizar(t)
    m = _ORDEN_AL_ASISTENTE.match(n)
    if m and len(n) == len(t):
        t = t[m.end():]
    t = t.strip(' ,;:-–y').strip()
    t = re.sub(r'^(?:y|e|ademas|además|tambien|también)\s+', '', t, flags=re.I)
    t = re.sub(r'\b(\w+?(?:cion|sion))d e\b', r'\1 de', t)               # «organizaciond e» → «organizacion de»
    t = re.sub(r'\b(\w+?)([cs])ion\b', r'\1\2ión', t)                     # -cion / -sion → -ción / -sión
    t = re.sub(r'(\w{3,}) (en caso de|si se requiere|si se requieren)\b', r'\1; \2', t)   # frase larga sin pausa
    t = re.sub(r'\b[A-Za-z]+\b', lambda w: _TILDES.get(w.group(0).lower(), w.group(0))
               if w.group(0).islower() else w.group(0), t)
    if not t:
        return ''
    t = t[0].upper() + t[1:]
    if len(t) > MAX_LARGO_NOTA:
        t = t[:MAX_LARGO_NOTA - 1].rsplit(' ', 1)[0]
    return t if t.endswith(('.', '!', ')')) else t.rstrip(',;:') + '.'


def seccion_de(texto):
    n = normalizar(texto)
    for patron, seccion in _SECCION_DE:
        if re.search(patron, n):
            return seccion
    return 'Alcance del servicio'


def condiciones_del_negocio(indicaciones):
    """[(sección, nota)] con las condiciones propias que escribió el negocio."""
    def abusiva(texto):
        n = normalizar(texto)
        return any(re.search(p, n) for p in _PEDIDOS_ABUSIVOS) or es_abusiva(texto)

    frases = []
    for frase in re.split(r'[.;\n]+(?:\s|$)|\n', str(indicaciones or '')):
        # «el anticipo no es reembolsable y el transporte va aparte»: se separa y se
        # conserva la parte válida.
        frases += (re.split(r'\s+y\s+(?=(?:el|la|los|las)\s)', frase, flags=re.I) if abusiva(frase) else [frase])
    salida = []
    for frase in frases:
        frase = ' '.join(frase.split())
        n = normalizar(frase)
        if not frase or frase.startswith('¿') or frase.endswith('?'):
            continue
        if abusiva(frase):
            continue                                      # va como aviso, nunca como nota
        if _ORDEN_DE_ESTILO.match(n):
            continue                                      # «hazlo más corto»: es para la IA
        nota = redactar_condicion(_quitar(frase, _VALORES))
        palabras = re.findall(r'[a-záéíóúñü]{3,}', nota.lower())
        if len(palabras) >= 3 and len(nota) >= 15 and not cita_norma_no_permitida(nota):
            salida.append((seccion_de(nota), nota))
    return salida[:4]


# ── Sugerencias base (sin IA) ─────────────────────────────────────────────────
def contexto(items, cliente=None, indicaciones=''):
    """Lo que se sabe de la cotización, sin datos personales del cliente."""
    items = [i for i in (items or []) if str(i.get('descripcion') or '').strip()]
    cliente = cliente or {}
    valores, avisos = leer_indicaciones(indicaciones)
    return {
        'items': items,
        'categorias': categorias_de(items),
        'hay_bienes': any(not es_servicio(i.get('descripcion')) for i in items),
        'hay_servicios': any(es_servicio(i.get('descripcion')) for i in items),
        'con_iva': any(float(i.get('iva') or 0) > 0 for i in items),
        'cliente': tipo_cliente(cliente.get('nombre'), cliente.get('documento')),
        'ciudad': str(cliente.get('ciudad') or '').strip()[:60],
        'valores': valores,
        'avisos': avisos,
        'condiciones': condiciones_del_negocio(indicaciones),
        'indicaciones': ' '.join(str(indicaciones or '').split())[:500],
    }


def _llenar(texto, valores, defectos):
    def valor(clave, defecto):
        return valores.get(clave) or defectos.get(clave) or defecto
    return (texto.replace('{vigencia}', valor('vigencia', '[15]'))
                 .replace('{anticipo}', valor('anticipo', '[50]'))
                 .replace('{entrega}', valor('entrega', '[5]'))
                 .replace('{garantia}', valor('garantia', '[3 meses]')))


def _sin_corchetes_de(valores, texto):
    """Si el negocio dio el valor, quita los corchetes que lo rodeaban («[60]» → «60»)."""
    for v in valores.values():
        texto = texto.replace(f'[{v}]', v)
    return texto


def clausulas_para(ctx):
    """(sección, texto) que aplican a esta cotización, en orden de prioridad."""
    return [(s, t) for s, t, _ in clausulas_con_origen(ctx)]


def clausulas_con_origen(ctx):
    """(sección, texto, propia): propia = viene del tipo de servicio o de una indicación
    del negocio (se conserva antes que las generales al recortar)."""
    v = ctx['valores']
    # Las condiciones propias del negocio van primero en su sección (y la vuelven propia).
    condiciones = ctx.get('condiciones') or []
    salida = list(condiciones) + [COMUNES['vigencia']]
    propias = {s for s, _ in condiciones}
    dice_materiales = any('material' in normalizar(t) for _, t in condiciones)
    for c in ctx['categorias']:
        datos = CATEGORIAS[c]
        defectos = {k: datos[k] for k in ('garantia', 'entrega') if k in datos}
        for clausula in datos['clausulas']:
            s, t = clausula[0], clausula[1]
            if len(clausula) > 2 and clausula[2] == 'servicio' and not ctx['hay_servicios']:
                continue                                  # p. ej. «incluye instalación» en una venta sin instalación
            if dice_materiales and '[incluye / no incluye] los materiales' in t:
                continue                                  # el negocio ya dijo qué materiales incluye
            salida.append((s, _llenar(t, v, defectos)))
            propias.add(s)
    if ctx['hay_bienes'] and not (set(ctx['categorias']) & _SIN_GARANTIA_GENERICA):
        tiene = {s for s, _ in salida}
        salida += [(s, _llenar(t, v, {})) for s, t in BIENES
                   if not (s == 'Garantía' and 'Garantía' in tiene and t.startswith('Los productos nuevos'))
                   and not (s == 'Tiempos de entrega' and 'Tiempos de entrega' in tiene)]
    if ctx['hay_servicios'] and not any(s == 'Garantía' for s, _ in salida):
        salida.append(COMUNES['garantia_servicio'])
    salida.append(COMUNES['cambios_alcance'] if ctx['hay_servicios'] else COMUNES['moneda'])
    salida.append(COMUNES['pago_anticipo'] if ctx['hay_servicios'] else COMUNES['pago_contado'])
    salida.append(COMUNES['medios_pago'])
    if ctx['cliente'] == 'empresa':
        salida.append(COMUNES['mora'])
    sin_retracto = bool(set(ctx['categorias']) & _SIN_RETRACTO)
    if ctx['hay_servicios']:
        salida.append(COMUNES['cancelacion_justa'])
    if ctx['cliente'] == 'persona natural' and ctx['hay_bienes'] and not sin_retracto:
        salida.append(COMUNES['retracto'])
    salida.append(COMUNES['iva_incluido'] if ctx['con_iva'] else COMUNES['iva_no'])
    salida.append(COMUNES['factura'])
    if ctx['cliente'] == 'empresa':
        salida.append(COMUNES['retenciones'])
    salida.append(COMUNES['datos'])
    # Una indicación del negocio vuelve propia su sección (p. ej. «entrega en 8 días»).
    if v.get('entrega'):
        propias.add('Tiempos de entrega')
    if v.get('anticipo'):
        propias.add('Forma de pago')
    if v.get('garantia'):
        propias.add('Garantía')
    vistos, unicas = set(), []
    for s, t in salida:
        t = _sin_corchetes_de(v, _llenar(t, v, {}))
        if t not in vistos:
            vistos.add(t)
            unicas.append((s, t, s in propias))
    return unicas


def agrupar(pares, maximo_secciones=MAX_SECCIONES, maximo_notas=MAX_NOTAS_SECCION, propias=(),
            maximo_total=MAX_NOTAS):
    """[(sección, nota)] → [{'titulo', 'notas'}] en el orden de SECCIONES, con topes por
    sección, de secciones y de notas. Al recortar quedan primero las secciones `propias`
    (del tipo de servicio) y luego las de PRIORIDAD."""
    por_seccion = {}
    for s, t in pares:
        lista = por_seccion.setdefault(s, [])
        if len(lista) < maximo_notas and t not in lista:
            lista.append(t)

    def rango(s):
        return (0 if s in propias else 1, PRIORIDAD.index(s) if s in PRIORIDAD else len(PRIORIDAD))
    elegidas, total = [], 0
    for s in sorted(por_seccion, key=rango):
        if len(elegidas) >= maximo_secciones or total >= maximo_total:
            break
        cupo = maximo_total - total
        por_seccion[s] = por_seccion[s][:cupo]
        elegidas.append(s)
        total += len(por_seccion[s])
    orden = [s for s in SECCIONES if s in elegidas] + [s for s in elegidas if s not in SECCIONES]
    return [{'titulo': s, 'notas': por_seccion[s]} for s in orden]


def sugerencias_base(items, cliente=None, indicaciones='', notas_actuales='', ya_vistas=()):
    """Sugerencias sin IA: las cláusulas revisadas que aplican, organizadas, sin lo que ya
    está escrito ni lo que ya se le mostró al negocio; con la revisión de sus notas."""
    ctx = contexto(items, cliente, indicaciones)
    visto = lo_ya_visto(notas_actuales, ya_vistas)
    trios = [c for c in clausulas_con_origen(ctx) if not ya_escrita(c[1], visto)]
    propias = {s for s, _, propia in trios if propia}
    secciones = agrupar([(s, t) for s, t, _ in trios], propias=propias)
    todas = {n for s in secciones for n in s['notas']}
    return {'secciones': secciones, 'avisos': ctx['avisos'] + revisar_notas(notas_actuales),
            'de_tus_indicaciones': [t for _, t in ctx['condiciones'] if t in todas]}


def lo_ya_visto(notas_actuales='', ya_vistas=()):
    """Las notas del cuadro más las sugerencias que ya se le mostraron, una por línea."""
    return '\n'.join([str(notas_actuales or '')] + [str(v) for v in (ya_vistas or []) if v])


_VACIAS = {'para', 'como', 'esta', 'este', 'estos', 'estas', 'desde', 'sobre', 'entre', 'cada', 'todo', 'toda',
           'todos', 'todas', 'solo', 'cuando', 'donde', 'segun', 'hasta', 'dentro', 'mismo', 'misma', 'debe',
           'puede', 'pueden', 'cual', 'cuales', 'tiene', 'tienen', 'sera', 'seran', 'otro', 'otros', 'otra', 'otras',
           'ante', 'bajo', 'tras', 'pero', 'sino', 'tambien', 'ademas', 'aqui', 'caso', 'hace', 'haya', 'sean',
           'esto', 'ellos', 'ellas', 'nuestro', 'nuestra', 'usted', 'ustedes'}


def _raices(texto):
    """Raíces (5 letras) de las palabras con contenido, para comparar sin importar la redacción."""
    return {w[:5] for w in re.findall(r'[a-z]{4,}', normalizar(texto)) if w not in _VACIAS}


def cobertura(nota, texto):
    """Qué parte de las ideas de `nota` aparece en `texto` (0 a 1)."""
    r = _raices(nota)
    return len(r & _raices(texto)) / len(r) if r else 0.0


def ya_escrita(nota, notas_actuales):
    """¿La nota (o una muy parecida, dicha con otras palabras o con los [corchetes] ya
    llenos) está en lo que escribió el negocio o en lo que ya se le mostró?"""
    actual = normalizar(notas_actuales)
    if not actual.strip():
        return False
    if normalizar(nota)[:60] in actual:
        return True
    r = _raices(nota)
    if not r:
        return False
    for linea in str(notas_actuales).splitlines():
        if not linea.strip() or _es_titulo(linea):
            continue
        rl = _raices(linea)
        comun = len(r & rl)
        if comun / len(r) >= 0.6 or (comun >= 2 and comun / max(len(rl), 1) >= 0.75):
            return True
    return False


def revisar_notas(notas_actuales):
    """Avisos sobre lo que ya escribió el negocio: cláusulas abusivas o normas dudosas."""
    avisos = []
    for linea in str(notas_actuales or '').splitlines():
        t = _LINEA_VINETA.sub('', linea).strip()
        if not t or _es_titulo(linea):
            continue
        corta = t if len(t) <= 70 else t[:67].rsplit(' ', 1)[0] + '…'
        if es_abusiva(t):
            avisos.append(f'Revisa tu nota «{corta}»: quitar la garantía, negar devoluciones o reclamos, o quedarse con '
                          'todo el anticipo no es válido (art. 43 de la Ley 1480 de 2011). Te sugiero cambiarla por '
                          'las condiciones justas de las sugerencias.')
        elif cita_norma_no_permitida(t):
            avisos.append(f'Tu nota «{corta}» cita una norma que no está en la lista revisada: confírmala antes de '
                          'enviar la cotización.')
    return avisos[:3]


# ── Texto organizado (cuadro de notas) y bloques (PDF) ─────────────────────────
VINETA = '•'
_LINEA_VINETA = re.compile(r'^\s*[•\-\*–·]\s+')


def a_texto(secciones):
    """[{'titulo', 'notas'}] → texto para el cuadro de notas:

    VIGENCIA Y PRECIOS
    • nota
    """
    bloques = []
    for s in secciones or []:
        notas = [n for n in s.get('notas') or [] if str(n).strip()]
        if not notas:
            continue
        lineas = [str(s.get('titulo') or '').strip().upper()] if s.get('titulo') else []
        lineas += [f'{VINETA} {str(n).strip()}' for n in notas]
        bloques.append('\n'.join(lineas))
    return '\n\n'.join(bloques)


def _es_titulo(linea):
    t = linea.strip()
    if not t or len(t) > 60 or _LINEA_VINETA.match(t):
        return False
    letras = [c for c in t if c.isalpha()]
    return (t.endswith(':') and len(t) <= 50) or (len(letras) >= 3 and t.upper() == t)


def bloques(notas):
    """Texto de notas → [{'titulo': str, 'lineas': [{'vineta': bool, 'texto': str}]}] para el PDF.
    Títulos: líneas en MAYÚSCULAS o que terminan en «:». Viñetas: «•», «-», «*», «–»."""
    salida, actual = [], None
    for linea in str(notas or '').splitlines():
        if not linea.strip():
            continue
        if _es_titulo(linea):
            actual = {'titulo': linea.strip().rstrip(':').strip(), 'lineas': []}
            salida.append(actual)
            continue
        if actual is None:
            actual = {'titulo': '', 'lineas': []}
            salida.append(actual)
        vineta = bool(_LINEA_VINETA.match(linea))
        actual['lineas'].append({'vineta': vineta, 'texto': _LINEA_VINETA.sub('', linea).strip()})
    return [b for b in salida if b['titulo'] or b['lineas']]
