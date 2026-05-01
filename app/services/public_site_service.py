"""
services/public_site_service.py - Configuracion estructurada del sitio publico.

Centraliza la lectura y escritura del contenido expuesto antes del login
usando tablas propias del modulo:

- public_site_settings
- public_site_blocks
- public_site_items

Mantiene compatibilidad con instalaciones existentes sincronizando valores
relevantes hacia ``cliente_config`` y ``config_secciones`` cuando aplica.
"""

from functools import lru_cache
import os
import uuid

from database import get_db_cursor


def _bool_text(value):
    return 'true' if bool(value) else 'false'


def _parse_bool(value, default=False):
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in ('1', 'true', 'si', 'sí', 'yes', 'on'):
        return True
    if normalized in ('0', 'false', 'no', 'off'):
        return False
    return default


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@lru_cache(maxsize=32)
def _table_exists(table_name):
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT to_regclass(%s) AS regclass_name", (f'public.{table_name}',))
            row = cur.fetchone()
            return bool(row and row['regclass_name'])
    except Exception:
        return False


def clear_public_site_cache():
    _table_exists.cache_clear()


PUBLIC_SECTION_FIELDS = [
    {
        'key': 'mostrar_modulo_ventas',
        'label': 'Tienda y carrito',
        'description': 'Muestra productos, detalle de producto, carrito y accesos de compra.',
        'default': True,
    },
    {
        'key': 'mostrar_about',
        'label': 'Bloque quienes somos',
        'description': 'Muestra la seccion descriptiva principal del home.',
        'default': True,
    },
    {
        'key': 'mostrar_mision_vision',
        'label': 'Mision y vision',
        'description': 'Activa los bloques institucionales de mision y vision.',
        'default': True,
    },
    {
        'key': 'mostrar_publicaciones',
        'label': 'Novedades del home',
        'description': 'Muestra las publicaciones destacadas del inicio.',
        'default': True,
    },
    {
        'key': 'mostrar_mapa',
        'label': 'Mapa de ubicacion',
        'description': 'Activa el mapa embebido en la seccion de contacto.',
        'default': True,
    },
    {
        'key': 'mostrar_contacto',
        'label': 'Formulario de contacto',
        'description': 'Muestra el formulario de contacto del home.',
        'default': True,
    },
    {
        'key': 'mostrar_nav_productos',
        'label': 'Menu publico: Productos',
        'description': 'Muestra el acceso a productos en el menu superior.',
        'default': True,
    },
    {
        'key': 'mostrar_nav_servicios',
        'label': 'Menu publico: Servicios',
        'description': 'Muestra el acceso a servicios en el menu superior.',
        'default': True,
    },
    {
        'key': 'mostrar_nav_quienes_somos',
        'label': 'Menu publico: Quienes somos',
        'description': 'Muestra el acceso rapido a la seccion institucional.',
        'default': True,
    },
    {
        'key': 'mostrar_nav_contacto',
        'label': 'Menu publico: Contactanos',
        'description': 'Muestra el acceso rapido a la seccion de contacto.',
        'default': True,
    },
]

PUBLIC_BRANDING_FIELDS = [
    {
        'key': 'empresa_nombre',
        'label': 'Nombre comercial',
        'description': 'Nombre visible del sitio y de la empresa.',
        'type': 'text',
        'group': 'empresa',
        'default': 'CyberShop',
        'order': 1,
    },
    {
        'key': 'empresa_tagline',
        'label': 'Mensaje corto de marca',
        'description': 'Texto breve usado en el pie de pagina del sitio publico.',
        'type': 'text',
        'group': 'sitio_publico',
        'default': 'Soluciones tecnológicas pensadas para crecer contigo.',
        'order': 10,
    },
    {
        'key': 'empresa_email',
        'label': 'Correo publico',
        'description': 'Correo visible para clientes y formularios.',
        'type': 'email',
        'group': 'empresa',
        'default': 'cybershop.digitalsales@gmail.com',
        'order': 2,
    },
    {
        'key': 'contacto_email_destino',
        'label': 'Correo destino del formulario',
        'description': 'Destino interno de los mensajes enviados desde el home.',
        'type': 'email',
        'group': 'sitio_publico',
        'default': 'cybershop.digitalsales@gmail.com',
        'order': 11,
    },
    {
        'key': 'empresa_telefono',
        'label': 'Telefono publico',
        'description': 'Telefono visible en la comunicacion publica.',
        'type': 'tel',
        'group': 'empresa',
        'default': '3015963776',
        'order': 3,
    },
    {
        'key': 'empresa_whatsapp',
        'label': 'WhatsApp',
        'description': 'Numero en formato internacional para el boton flotante.',
        'type': 'text',
        'group': 'empresa',
        'default': '573027974969',
        'order': 4,
    },
    {
        'key': 'empresa_direccion',
        'label': 'Direccion',
        'description': 'Direccion visible para clientes.',
        'type': 'text',
        'group': 'empresa',
        'default': '',
        'order': 5,
    },
    {
        'key': 'empresa_website',
        'label': 'Sitio web corporativo',
        'description': 'URL oficial mostrable en documentos y secciones de contacto.',
        'type': 'url',
        'group': 'empresa',
        'default': '',
        'order': 6,
    },
    {
        'key': 'empresa_maps_embed',
        'label': 'Mapa embebido',
        'description': 'URL completa del mapa embebido de Google Maps.',
        'type': 'url',
        'group': 'empresa',
        'default': 'https://www.google.com/maps/embed?pb=!1m18!1m12!1m3!1d3976.1438661161997!2d-74.12405722491505!3d4.7450433952301445!2m3!1f0!2f0!3f0!3m2!1i1024!2i768!4f13.1!3m3!1m2!1s0x8e3f8481ac8fae15%3A0xd086f2615f6ea83!2sCra.%20151%20%23136a11%2C%20Suba%2C%20Bogot%C3%A1!5e0!3m2!1ses!2sco!4v1737344695200!5m2!1ses!2sco',
        'order': 7,
    },
    {
        'key': 'empresa_facebook',
        'label': 'Facebook',
        'description': 'URL de la red social.',
        'type': 'url',
        'group': 'empresa',
        'default': '#',
        'order': 8,
    },
    {
        'key': 'empresa_instagram',
        'label': 'Instagram',
        'description': 'URL de la red social.',
        'type': 'url',
        'group': 'empresa',
        'default': '#',
        'order': 9,
    },
    {
        'key': 'empresa_linkedin',
        'label': 'LinkedIn',
        'description': 'URL de la red social.',
        'type': 'url',
        'group': 'empresa',
        'default': '#',
        'order': 10,
    },
    {
        'key': 'empresa_youtube',
        'label': 'YouTube',
        'description': 'URL de la red social.',
        'type': 'url',
        'group': 'empresa',
        'default': '#',
        'order': 11,
    },
    {
        'key': 'empresa_twitter',
        'label': 'X / Twitter',
        'description': 'URL de la red social.',
        'type': 'url',
        'group': 'empresa',
        'default': '#',
        'order': 12,
    },
    {
        'key': 'empresa_copyright',
        'label': 'Texto de copyright',
        'description': 'Texto visible en footer y plantillas.',
        'type': 'text',
        'group': 'empresa',
        'default': 'CyberShop',
        'order': 13,
    },
    {
        'key': 'empresa_logo_url',
        'label': 'Ruta del logo',
        'description': 'Se actualiza automaticamente al subir un logo desde este modulo.',
        'type': 'text',
        'group': 'sitio_publico',
        'default': '/static/img/Logo.png',
        'order': 12,
    },
]

_PUBLIC_COLOR_FIELDS = [
    # (key, label, default, description, ui_group)
    ('color_secundario',        'Navbar y footer',           '#0e1b33', 'Fondo del navbar superior y del footer del sitio.',                 'estructura'),
    ('color_transicion',        'Gradiente del header',      '#16315f', 'Segundo tono del degradado del header y secciones destacadas.',     'estructura'),
    ('color_fondo_destacado',   'Fondo de bloques claros',   '#edf3ff', 'Fondo de secciones como Quiénes somos y bloques institucionales.',  'estructura'),
    ('color_primario',          'Color principal',           '#122C94', 'Encabezados, links del admin y primer tono de botones primarios.',  'botones'),
    ('color_primario_oscuro',   'Color principal oscuro',    '#091C5A', 'Hover y variante oscura del color principal. Sidebar del admin.',   'botones'),
    ('color_botones',           'Botones secundarios',       '#122C94', 'Botones de acción secundaria en el sitio público.',                 'botones'),
    ('color_hover_menu',        'Hover del menú admin',      '#fb8500', 'Resaltado al pasar el cursor sobre el menú lateral del admin.',     'botones'),
    ('color_acento',            'Acento principal',          '#e60023', 'Badges, etiquetas destacadas y precios tachados.',                  'acentos'),
    ('color_acento_secundario', 'Acento secundario',         '#fb8500', 'Iconos de búsqueda, métodos de pago y acentos complementarios.',    'acentos'),
    ('color_producto_boton',    'Precio en tarjeta',         '#091C5A', 'Color del precio en la tarjeta del catálogo y en el popup de producto.', 'catalogo'),
    ('color_producto_popup',    'Tag y botón "Ver detalles"','#122C94', 'Tag de categoría, título del popup y botón outline "Ver detalles".',  'catalogo'),
    ('color_exito',             'Botón "Añadir al carrito"', '#28a745', 'Botón principal de compra (tarjeta, popup) y botón "Pagar" en carrito.', 'catalogo'),
    ('color_exito_hover',       'Hover botón "Añadir"',      '#218838', 'Estado hover del botón de compra en tarjeta y popup.',                'catalogo'),
    ('color_carrito',           'Encabezado del carrito',    '#122C94', 'Cabecera de la tabla del carrito y botón flotante de acceso rápido.', 'carrito'),
    ('color_carrito_hover',     'Hover botones carrito',     '#091C5A', 'Estado hover de los botones +/- dentro del panel del carrito.',      'carrito'),
    ('color_alerta_fondo',      'Fondo de alertas',          '#ffffff', 'Fondo del cuadro de diálogo de confirmaciones y errores.',         'alertas'),
    ('color_alerta_texto',      'Texto de alertas',          '#333333', 'Color del texto principal dentro de los diálogos de alerta.',      'alertas'),
    ('color_alerta_confirmar',  'Botón confirmar',           '#122C94', 'Botón de acción positiva (Sí, Aceptar) en los diálogos.',          'alertas'),
    ('color_alerta_cancelar',   'Botón cancelar',            '#dc3545', 'Botón de cancelación o rechazo en los diálogos.',                  'alertas'),
]

PUBLIC_COLOR_FIELDS = [
    {
        'key': key,
        'label': label,
        'description': description,
        'type': 'color',
        'group': 'colores',
        'ui_group': ui_group,
        'default': default,
        'order': 100 + index,
    }
    for index, (key, label, default, description, ui_group) in enumerate(_PUBLIC_COLOR_FIELDS, start=1)
]

PUBLIC_LANDING_FIELDS = [
    {
        'key': 'home_about_title',
        'label': 'Titulo quienes somos',
        'description': 'Titulo principal del bloque institucional del home.',
        'type': 'text',
        'group': 'sitio_publico',
        'default': '',
        'order': 20,
    },
    {
        'key': 'home_about_intro',
        'label': 'Texto principal quienes somos',
        'description': 'Primer parrafo del bloque quienes somos.',
        'type': 'textarea',
        'group': 'sitio_publico',
        'default': (
            'Somos una empresa comprometida con la innovación y la excelencia tecnológica. '
            'Nuestro objetivo es ofrecer soluciones integrales que impulsen el desarrollo '
            'de nuestros clientes y optimicen sus operaciones. Nos destacamos por nuestra '
            'experiencia, dedicación y enfoque personalizado, siempre buscando superar '
            'expectativas.'
        ),
        'order': 21,
    },
    {
        'key': 'home_about_body',
        'label': 'Texto complementario quienes somos',
        'description': 'Segundo parrafo del bloque institucional.',
        'type': 'textarea',
        'group': 'sitio_publico',
        'default': (
            'Con un equipo altamente capacitado y una visión orientada al futuro, trabajamos '
            'para convertirnos en tu aliado estratégico en tecnología. Transformamos desafíos '
            'en oportunidades, asegurándonos de que cada proyecto sea un éxito.'
        ),
        'order': 22,
    },
    {
        'key': 'home_mision_titulo',
        'label': 'Titulo misión',
        'description': 'Titulo del bloque de mision.',
        'type': 'text',
        'group': 'sitio_publico',
        'default': 'Misión',
        'order': 23,
    },
    {
        'key': 'home_mision_texto',
        'label': 'Texto misión',
        'description': 'Contenido completo de la misión.',
        'type': 'textarea',
        'group': 'sitio_publico',
        'default': (
            'Nos dedicamos a ofrecer soluciones tecnológicas integrales y personalizadas que '
            'impulsen el crecimiento y la eficiencia de nuestros clientes. A través de nuestra '
            'experiencia, dedicación y enfoque innovador, buscamos optimizar sus operaciones, '
            'superar expectativas y convertirnos en su aliado estratégico en el mundo digital.'
        ),
        'order': 24,
    },
    {
        'key': 'home_vision_titulo',
        'label': 'Titulo visión',
        'description': 'Titulo del bloque de vision.',
        'type': 'text',
        'group': 'sitio_publico',
        'default': 'Visión',
        'order': 25,
    },
    {
        'key': 'home_vision_texto',
        'label': 'Texto visión',
        'description': 'Contenido completo de la visión.',
        'type': 'textarea',
        'group': 'sitio_publico',
        'default': (
            'Ser reconocidos como líderes en innovación y excelencia tecnológica, siendo el '
            'referente principal para empresas y personas que buscan soluciones confiables y '
            'vanguardistas. Aspiramos a construir un futuro donde la tecnología sea accesible, '
            'eficiente y transformadora.'
        ),
        'order': 26,
    },
    {
        'key': 'home_publicaciones_titulo',
        'label': 'Titulo novedades',
        'description': 'Encabezado del bloque de publicaciones del home.',
        'type': 'text',
        'group': 'sitio_publico',
        'default': 'Novedades',
        'order': 27,
    },
    {
        'key': 'home_contacto_titulo',
        'label': 'Titulo contacto',
        'description': 'Titulo visible sobre el formulario de contacto.',
        'type': 'text',
        'group': 'sitio_publico',
        'default': 'Contáctanos',
        'order': 28,
    },
    {
        'key': 'home_contacto_intro',
        'label': 'Texto contacto',
        'description': 'Mensaje corto para invitar al contacto.',
        'type': 'textarea',
        'group': 'sitio_publico',
        'default': 'Cuéntanos lo que necesitas y nuestro equipo te responderá lo antes posible.',
        'order': 29,
    },
    {
        'key': 'servicios_hero_titulo',
        'label': 'Titulo de la pagina de servicios',
        'description': 'Titulo principal de la pagina /servicios.',
        'type': 'text',
        'group': 'sitio_publico',
        'default': 'Servicios',
        'order': 30,
    },
    {
        'key': 'servicios_hero_subtitulo',
        'label': 'Subtitulo de la pagina de servicios',
        'description': 'Mensaje corto de apertura de la pagina /servicios.',
        'type': 'textarea',
        'group': 'sitio_publico',
        'default': 'Presentamos soluciones especializadas para operación, soporte y crecimiento digital.',
        'order': 31,
    },
]

PUBLIC_BLOCK_DEFINITIONS = {
    'about': {
        'block_type': 'landing',
        'title_key': 'home_about_title',
        'body_key': 'home_about_intro',
        'extra_body_key': 'home_about_body',
        'sort_order': 10,
        'default': {
            'title': '',
            'body': next(field['default'] for field in PUBLIC_LANDING_FIELDS if field['key'] == 'home_about_intro'),
            'extra_body': next(field['default'] for field in PUBLIC_LANDING_FIELDS if field['key'] == 'home_about_body'),
        },
    },
    'mission': {
        'block_type': 'landing',
        'title_key': 'home_mision_titulo',
        'body_key': 'home_mision_texto',
        'sort_order': 20,
        'default': {
            'title': next(field['default'] for field in PUBLIC_LANDING_FIELDS if field['key'] == 'home_mision_titulo'),
            'body': next(field['default'] for field in PUBLIC_LANDING_FIELDS if field['key'] == 'home_mision_texto'),
            'extra_body': '',
        },
    },
    'vision': {
        'block_type': 'landing',
        'title_key': 'home_vision_titulo',
        'body_key': 'home_vision_texto',
        'sort_order': 30,
        'default': {
            'title': next(field['default'] for field in PUBLIC_LANDING_FIELDS if field['key'] == 'home_vision_titulo'),
            'body': next(field['default'] for field in PUBLIC_LANDING_FIELDS if field['key'] == 'home_vision_texto'),
            'extra_body': '',
        },
    },
    'publications': {
        'block_type': 'landing',
        'title_key': 'home_publicaciones_titulo',
        'sort_order': 40,
        'default': {
            'title': next(field['default'] for field in PUBLIC_LANDING_FIELDS if field['key'] == 'home_publicaciones_titulo'),
            'body': '',
            'extra_body': '',
        },
    },
    'contact': {
        'block_type': 'landing',
        'title_key': 'home_contacto_titulo',
        'body_key': 'home_contacto_intro',
        'sort_order': 50,
        'default': {
            'title': next(field['default'] for field in PUBLIC_LANDING_FIELDS if field['key'] == 'home_contacto_titulo'),
            'body': next(field['default'] for field in PUBLIC_LANDING_FIELDS if field['key'] == 'home_contacto_intro'),
            'extra_body': '',
        },
    },
    'services_hero': {
        'block_type': 'landing',
        'title_key': 'servicios_hero_titulo',
        'body_key': 'servicios_hero_subtitulo',
        'sort_order': 60,
        'default': {
            'title': next(field['default'] for field in PUBLIC_LANDING_FIELDS if field['key'] == 'servicios_hero_titulo'),
            'body': next(field['default'] for field in PUBLIC_LANDING_FIELDS if field['key'] == 'servicios_hero_subtitulo'),
            'extra_body': '',
        },
    },
}

PUBLIC_LANDING_FIELD_TO_BLOCK = {}
for slug, definition in PUBLIC_BLOCK_DEFINITIONS.items():
    if definition.get('title_key'):
        PUBLIC_LANDING_FIELD_TO_BLOCK[definition['title_key']] = (slug, 'title')
    if definition.get('body_key'):
        PUBLIC_LANDING_FIELD_TO_BLOCK[definition['body_key']] = (slug, 'body')
    if definition.get('extra_body_key'):
        PUBLIC_LANDING_FIELD_TO_BLOCK[definition['extra_body_key']] = (slug, 'extra_body')


PUBLIC_ITEM_TYPES = {
    'slide': {
        'label': 'Slides',
        'singular': 'slide',
        'legacy_table': 'slides_home',
        'sort_default': 10,
    },
    'publication': {
        'label': 'Publicaciones',
        'singular': 'publicación',
        'legacy_table': 'publicaciones_home',
        'sort_default': 10,
    },
    'service': {
        'label': 'Servicios',
        'singular': 'servicio',
        'legacy_table': 'servicios_home',
        'sort_default': 10,
    },
}


PUBLIC_FIELD_BY_KEY = {
    field['key']: field
    for field in PUBLIC_BRANDING_FIELDS + PUBLIC_COLOR_FIELDS + PUBLIC_LANDING_FIELDS
}
PUBLIC_SECTION_BY_KEY = {field['key']: field for field in PUBLIC_SECTION_FIELDS}

PUBLIC_STRUCTURED_SETTING_FIELDS = (
    PUBLIC_BRANDING_FIELDS
    + PUBLIC_COLOR_FIELDS
    + [
        {
            'key': field['key'],
            'label': field['label'],
            'description': field['description'],
            'type': 'boolean',
            'group': 'sitio_publico_secciones',
            'default': _bool_text(field['default']),
            'order': 300 + index,
        }
        for index, field in enumerate(PUBLIC_SECTION_FIELDS, start=1)
    ]
)
PUBLIC_STRUCTURED_SETTING_BY_KEY = {field['key']: field for field in PUBLIC_STRUCTURED_SETTING_FIELDS}


def _legacy_cliente_config_values():
    values = {}
    if not _table_exists('cliente_config'):
        return values

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT clave, valor FROM cliente_config')
            values = {row['clave']: row['valor'] for row in cur.fetchall()}
    except Exception:
        values = {}
    return values


def _legacy_section_values():
    values = {}
    if not _table_exists('config_secciones'):
        return values

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT clave, valor FROM config_secciones')
            values = {row['clave']: row['valor'] for row in cur.fetchall()}
    except Exception:
        values = {}
    return values


def _structured_settings_values():
    if not _table_exists('public_site_settings'):
        return {}
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT key, value FROM public_site_settings')
            return {row['key']: row['value'] for row in cur.fetchall()}
    except Exception:
        return {}


def _structured_blocks_map():
    if not _table_exists('public_site_blocks'):
        return {}
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(
                """
                SELECT id, slug, block_type, title, subtitle, body, extra_body,
                       sort_order, is_active
                FROM public_site_blocks
                ORDER BY sort_order ASC, id ASC
                """
            )
            return {row['slug']: dict(row) for row in cur.fetchall()}
    except Exception:
        return {}


def _structured_items_exist(item_type):
    if not _table_exists('public_site_items'):
        return False
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(
                'SELECT 1 FROM public_site_items WHERE item_type = %s LIMIT 1',
                (item_type,),
            )
            return cur.fetchone() is not None
    except Exception:
        return False


def _ensure_cliente_config_table():
    with get_db_cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS cliente_config (
                clave       VARCHAR PRIMARY KEY,
                valor       TEXT,
                tipo        VARCHAR DEFAULT 'text',
                grupo       VARCHAR DEFAULT 'general',
                descripcion TEXT,
                orden       INTEGER DEFAULT 0
            )
            """
        )


def _ensure_config_secciones_table():
    with get_db_cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS config_secciones (
                clave       VARCHAR PRIMARY KEY,
                valor       TEXT NOT NULL DEFAULT 'true',
                descripcion TEXT
            )
            """
        )


def _ensure_public_site_tables():
    with get_db_cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public_site_settings (
                key         VARCHAR PRIMARY KEY,
                value       TEXT,
                value_type  VARCHAR NOT NULL DEFAULT 'text',
                group_name  VARCHAR NOT NULL DEFAULT 'general',
                description TEXT,
                sort_order  INTEGER NOT NULL DEFAULT 0,
                updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public_site_blocks (
                id          SERIAL PRIMARY KEY,
                slug        VARCHAR NOT NULL UNIQUE,
                block_type  VARCHAR NOT NULL DEFAULT 'landing',
                title       TEXT,
                subtitle    TEXT,
                body        TEXT,
                extra_body  TEXT,
                sort_order  INTEGER NOT NULL DEFAULT 0,
                is_active   BOOLEAN NOT NULL DEFAULT TRUE,
                updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public_site_items (
                id          SERIAL PRIMARY KEY,
                item_type   VARCHAR NOT NULL,
                title       TEXT,
                subtitle    TEXT,
                description TEXT,
                image_url   TEXT,
                cta_label   TEXT,
                cta_url     TEXT,
                extra_text  TEXT,
                sort_order  INTEGER NOT NULL DEFAULT 0,
                is_active   BOOLEAN NOT NULL DEFAULT TRUE,
                created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            'CREATE INDEX IF NOT EXISTS idx_public_site_settings_group ON public_site_settings(group_name, sort_order)'
        )
        cur.execute(
            'CREATE INDEX IF NOT EXISTS idx_public_site_blocks_type ON public_site_blocks(block_type, sort_order)'
        )
        cur.execute(
            'CREATE INDEX IF NOT EXISTS idx_public_site_items_type ON public_site_items(item_type, sort_order, is_active)'
        )
    clear_public_site_cache()


def _upsert_cliente_config(key, value):
    field = PUBLIC_FIELD_BY_KEY.get(key)
    if not field:
        return

    _ensure_cliente_config_table()
    with get_db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (clave)
            DO UPDATE SET
                valor = EXCLUDED.valor,
                tipo = EXCLUDED.tipo,
                grupo = EXCLUDED.grupo,
                descripcion = EXCLUDED.descripcion,
                orden = EXCLUDED.orden
            """,
            (
                key,
                value,
                field['type'],
                field['group'],
                field['description'],
                field['order'],
            ),
        )


def _upsert_config_seccion(key, enabled):
    field = PUBLIC_SECTION_BY_KEY.get(key)
    if not field:
        return

    _ensure_config_secciones_table()
    with get_db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO config_secciones (clave, valor, descripcion)
            VALUES (%s, %s, %s)
            ON CONFLICT (clave)
            DO UPDATE SET
                valor = EXCLUDED.valor,
                descripcion = EXCLUDED.descripcion
            """,
            (key, _bool_text(enabled), field['description']),
        )


def _upsert_public_site_setting(key, value):
    field = PUBLIC_STRUCTURED_SETTING_BY_KEY.get(key)
    if not field:
        return

    _ensure_public_site_tables()
    with get_db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO public_site_settings (key, value, value_type, group_name, description, sort_order, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (key)
            DO UPDATE SET
                value = EXCLUDED.value,
                value_type = EXCLUDED.value_type,
                group_name = EXCLUDED.group_name,
                description = EXCLUDED.description,
                sort_order = EXCLUDED.sort_order,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                key,
                value,
                field['type'],
                field['group'],
                field['description'],
                field['order'],
            ),
        )


def _insert_public_site_setting_if_missing(key, value):
    field = PUBLIC_STRUCTURED_SETTING_BY_KEY.get(key)
    if not field:
        return

    with get_db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO public_site_settings (key, value, value_type, group_name, description, sort_order, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (key) DO NOTHING
            """,
            (
                key,
                value,
                field['type'],
                field['group'],
                field['description'],
                field['order'],
            ),
        )


def _upsert_public_block(slug, **values):
    definition = PUBLIC_BLOCK_DEFINITIONS.get(slug)
    if not definition:
        return

    defaults = definition['default']
    title = values.get('title', defaults.get('title', ''))
    subtitle = values.get('subtitle', '')
    body = values.get('body', defaults.get('body', ''))
    extra_body = values.get('extra_body', defaults.get('extra_body', ''))
    sort_order = _safe_int(values.get('sort_order'), definition['sort_order'])
    is_active = bool(values.get('is_active', True))

    _ensure_public_site_tables()
    with get_db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO public_site_blocks
                (slug, block_type, title, subtitle, body, extra_body, sort_order, is_active, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (slug)
            DO UPDATE SET
                block_type = EXCLUDED.block_type,
                title = EXCLUDED.title,
                subtitle = EXCLUDED.subtitle,
                body = EXCLUDED.body,
                extra_body = EXCLUDED.extra_body,
                sort_order = EXCLUDED.sort_order,
                is_active = EXCLUDED.is_active,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                slug,
                definition['block_type'],
                title,
                subtitle,
                body,
                extra_body,
                sort_order,
                is_active,
            ),
        )


def _insert_public_block_if_missing(slug, **values):
    definition = PUBLIC_BLOCK_DEFINITIONS.get(slug)
    if not definition:
        return

    defaults = definition['default']
    title = values.get('title', defaults.get('title', ''))
    subtitle = values.get('subtitle', '')
    body = values.get('body', defaults.get('body', ''))
    extra_body = values.get('extra_body', defaults.get('extra_body', ''))
    sort_order = _safe_int(values.get('sort_order'), definition['sort_order'])
    is_active = bool(values.get('is_active', True))

    with get_db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO public_site_blocks
                (slug, block_type, title, subtitle, body, extra_body, sort_order, is_active, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (slug) DO NOTHING
            """,
            (
                slug,
                definition['block_type'],
                title,
                subtitle,
                body,
                extra_body,
                sort_order,
                is_active,
            ),
        )


def _save_public_asset(file_storage, root_path, prefix='public'):
    if not file_storage or not file_storage.filename:
        return None

    _, ext = os.path.splitext(file_storage.filename)
    ext = ext.lower()
    if ext not in ('.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif'):
        ext = '.png'

    relative_dir = os.path.join('static', 'media', 'public_site')
    absolute_dir = os.path.join(root_path, relative_dir)
    os.makedirs(absolute_dir, exist_ok=True)

    filename = f'{prefix}_{uuid.uuid4().hex[:12]}{ext}'
    absolute_path = os.path.join(absolute_dir, filename)
    file_storage.save(absolute_path)
    return f'/static/media/public_site/{filename}'


def bootstrap_public_site_structure():
    _ensure_public_site_tables()

    legacy_settings = _legacy_cliente_config_values()
    legacy_sections = _legacy_section_values()

    for field in PUBLIC_BRANDING_FIELDS + PUBLIC_COLOR_FIELDS:
        _insert_public_site_setting_if_missing(
            field['key'],
            legacy_settings.get(field['key'], field['default']),
        )

    for field in PUBLIC_SECTION_FIELDS:
        _insert_public_site_setting_if_missing(
            field['key'],
            legacy_sections.get(field['key'], _bool_text(field['default'])),
        )

    for slug, definition in PUBLIC_BLOCK_DEFINITIONS.items():
        payload = dict(definition['default'])
        title_key = definition.get('title_key')
        body_key = definition.get('body_key')
        extra_body_key = definition.get('extra_body_key')

        if title_key:
            payload['title'] = legacy_settings.get(title_key, payload.get('title', ''))
        if body_key:
            payload['body'] = legacy_settings.get(body_key, payload.get('body', ''))
        if extra_body_key:
            payload['extra_body'] = legacy_settings.get(extra_body_key, payload.get('extra_body', ''))

        _insert_public_block_if_missing(slug, **payload)

    _bootstrap_public_items_from_legacy()


def _bootstrap_public_items_from_legacy():
    if not _table_exists('public_site_items'):
        return

    for item_type in PUBLIC_ITEM_TYPES:
        if _structured_items_exist(item_type):
            continue

        if item_type == 'slide' and _table_exists('slides_home'):
            try:
                with get_db_cursor(dict_cursor=True) as cur:
                    cur.execute(
                        """
                        SELECT imagen, titulo, descripcion, orden, activo
                        FROM slides_home
                        ORDER BY orden ASC, id ASC
                        """
                    )
                    rows = cur.fetchall()
                for row in rows:
                    _create_public_site_item(
                        item_type='slide',
                        title=row['titulo'],
                        description=row['descripcion'],
                        image_url=row['imagen'],
                        sort_order=row['orden'],
                        is_active=row['activo'],
                    )
            except Exception:
                pass

        if item_type == 'publication' and _table_exists('publicaciones_home'):
            try:
                with get_db_cursor(dict_cursor=True) as cur:
                    cur.execute(
                        """
                        SELECT titulo, descripcion, imagen, activo
                        FROM publicaciones_home
                        ORDER BY fecha_creacion DESC, id DESC
                        """
                    )
                    rows = cur.fetchall()
                for index, row in enumerate(rows, start=1):
                    _create_public_site_item(
                        item_type='publication',
                        title=row['titulo'],
                        description=row['descripcion'],
                        image_url=row['imagen'],
                        sort_order=index,
                        is_active=row['activo'],
                    )
            except Exception:
                pass

        if item_type == 'service' and _table_exists('servicios_home'):
            try:
                with get_db_cursor(dict_cursor=True) as cur:
                    cur.execute(
                        """
                        SELECT titulo, descripcion, beneficios, imagen, orden, activo
                        FROM servicios_home
                        ORDER BY orden ASC, id ASC
                        """
                    )
                    rows = cur.fetchall()
                for row in rows:
                    _create_public_site_item(
                        item_type='service',
                        title=row['titulo'],
                        description=row['descripcion'],
                        image_url=row['imagen'],
                        extra_text=row['beneficios'],
                        sort_order=row['orden'],
                        is_active=row['activo'],
                    )
            except Exception:
                pass


def _create_public_site_item(
    *,
    item_type,
    title='',
    subtitle='',
    description='',
    image_url='',
    cta_label='',
    cta_url='',
    extra_text='',
    sort_order=0,
    is_active=True,
):
    if item_type not in PUBLIC_ITEM_TYPES:
        return None

    _ensure_public_site_tables()
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            INSERT INTO public_site_items
                (item_type, title, subtitle, description, image_url, cta_label, cta_url,
                 extra_text, sort_order, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (
                item_type,
                title,
                subtitle,
                description,
                image_url,
                cta_label,
                cta_url,
                extra_text,
                _safe_int(sort_order),
                bool(is_active),
            ),
        )
        row = cur.fetchone()
        return row['id'] if row else None


def _legacy_home_items(item_type):
    if item_type == 'slide' and _table_exists('slides_home'):
        try:
            with get_db_cursor(dict_cursor=True) as cur:
                cur.execute(
                    """
                    SELECT id, imagen, titulo, descripcion, orden, activo
                    FROM slides_home
                    ORDER BY orden ASC, id ASC
                    """
                )
                return [
                    {
                        'id': row['id'],
                        'item_type': 'slide',
                        'title': row['titulo'] or '',
                        'subtitle': '',
                        'description': row['descripcion'] or '',
                        'image_url': row['imagen'] or '',
                        'cta_label': '',
                        'cta_url': '',
                        'extra_text': '',
                        'sort_order': row['orden'] or 0,
                        'is_active': row['activo'],
                    }
                    for row in cur.fetchall()
                ]
        except Exception:
            return []

    if item_type == 'publication' and _table_exists('publicaciones_home'):
        try:
            with get_db_cursor(dict_cursor=True) as cur:
                cur.execute(
                    """
                    SELECT id, titulo, descripcion, imagen, activo
                    FROM publicaciones_home
                    ORDER BY fecha_creacion DESC, id DESC
                    """
                )
                return [
                    {
                        'id': row['id'],
                        'item_type': 'publication',
                        'title': row['titulo'] or '',
                        'subtitle': '',
                        'description': row['descripcion'] or '',
                        'image_url': row['imagen'] or '',
                        'cta_label': '',
                        'cta_url': '',
                        'extra_text': '',
                        'sort_order': 0,
                        'is_active': row['activo'],
                    }
                    for row in cur.fetchall()
                ]
        except Exception:
            return []

    if item_type == 'service' and _table_exists('servicios_home'):
        try:
            with get_db_cursor(dict_cursor=True) as cur:
                cur.execute(
                    """
                    SELECT id, titulo, descripcion, beneficios, imagen, orden, activo
                    FROM servicios_home
                    ORDER BY orden ASC, id ASC
                    """
                )
                return [
                    {
                        'id': row['id'],
                        'item_type': 'service',
                        'title': row['titulo'] or '',
                        'subtitle': '',
                        'description': row['descripcion'] or '',
                        'image_url': row['imagen'] or '',
                        'cta_label': '',
                        'cta_url': '',
                        'extra_text': row['beneficios'] or '',
                        'sort_order': row['orden'] or 0,
                        'is_active': row['activo'],
                    }
                    for row in cur.fetchall()
                ]
        except Exception:
            return []

    return []


def get_public_site_items(item_type, *, include_inactive=False):
    if item_type not in PUBLIC_ITEM_TYPES:
        return []

    rows = _legacy_home_items(item_type)
    if rows:
        if include_inactive:
            return rows
        return [row for row in rows if row.get('is_active', True)]

    if _structured_items_exist(item_type):
        try:
            with get_db_cursor(dict_cursor=True) as cur:
                query = """
                    SELECT id, item_type, title, subtitle, description, image_url,
                           cta_label, cta_url, extra_text, sort_order, is_active,
                           created_at, updated_at
                    FROM public_site_items
                    WHERE item_type = %s
                """
                params = [item_type]
                if not include_inactive:
                    query += ' AND is_active = TRUE'
                query += ' ORDER BY sort_order ASC, created_at DESC, id ASC'
                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]
        except Exception:
            return []
    return []


def get_brand_config():
    structured = _structured_settings_values()
    legacy = _legacy_cliente_config_values()
    values = {}

    for field in PUBLIC_BRANDING_FIELDS + PUBLIC_COLOR_FIELDS:
        values[field['key']] = structured.get(
            field['key'],
            legacy.get(field['key'], field['default']),
        )

    landing_values = _get_landing_values()
    values.update(landing_values)

    if not values.get('empresa_logo_url'):
        values['empresa_logo_url'] = '/static/img/Logo.png'
    return values


def get_public_site_settings():
    settings = get_brand_config()
    return {field['key']: settings.get(field['key'], field['default']) for field in PUBLIC_FIELD_BY_KEY.values()}


def get_public_sections():
    structured = _structured_settings_values()
    legacy = _legacy_section_values()
    sections = {}

    for field in PUBLIC_SECTION_FIELDS:
        if field['key'] in structured:
            sections[field['key']] = _parse_bool(structured.get(field['key']), field['default'])
        elif field['key'] in legacy:
            sections[field['key']] = _parse_bool(legacy.get(field['key']), field['default'])
        else:
            sections[field['key']] = field['default']
    return sections


def is_public_section_enabled(section_key, default=True):
    return get_public_sections().get(section_key, default)


def get_public_menu_items(*, include_login=True):
    sections = get_public_sections()
    menu = [{'nombre': 'Inicio', 'url': 'public.index'}]

    if sections.get('mostrar_modulo_ventas', True) and sections.get('mostrar_nav_productos', True):
        menu.append({'nombre': 'Productos', 'url': 'public.productos'})
    if sections.get('mostrar_nav_servicios', True):
        menu.append({'nombre': 'Servicios', 'url': 'public.servicios'})
    if sections.get('mostrar_nav_quienes_somos', True):
        menu.append({'nombre': '¿Quienes Somos?', 'url': 'public.quienes_somos'})
    if sections.get('mostrar_nav_contacto', True):
        menu.append({'nombre': 'Contactanos', 'url': 'public.contactenos'})
    if include_login:
        menu.append({'nombre': 'Ingresar', 'url': 'auth.login'})

    return menu


def _get_landing_values():
    legacy = _legacy_cliente_config_values()
    blocks = _structured_blocks_map()
    values = {field['key']: field['default'] for field in PUBLIC_LANDING_FIELDS}

    if blocks:
        for slug, definition in PUBLIC_BLOCK_DEFINITIONS.items():
            block = blocks.get(slug, {})
            if definition.get('title_key'):
                values[definition['title_key']] = block.get('title') or definition['default'].get('title', '')
            if definition.get('body_key'):
                values[definition['body_key']] = block.get('body') or definition['default'].get('body', '')
            if definition.get('extra_body_key'):
                values[definition['extra_body_key']] = block.get('extra_body') or definition['default'].get('extra_body', '')

    for field in PUBLIC_LANDING_FIELDS:
        values[field['key']] = values.get(field['key']) or legacy.get(field['key'], field['default'])

    return values


def get_public_home_content():
    settings = get_public_site_settings()
    company_name = settings.get('empresa_nombre') or 'CyberShop'
    about_title = settings.get('home_about_title') or company_name

    return {
        'about_title': about_title,
        'about_intro': settings.get('home_about_intro'),
        'about_body': settings.get('home_about_body'),
        'mission_title': settings.get('home_mision_titulo'),
        'mission_text': settings.get('home_mision_texto'),
        'vision_title': settings.get('home_vision_titulo'),
        'vision_text': settings.get('home_vision_texto'),
        'publications_title': settings.get('home_publicaciones_titulo'),
        'contact_title': settings.get('home_contacto_titulo'),
        'contact_intro': settings.get('home_contacto_intro'),
        'services_hero_title': settings.get('servicios_hero_titulo'),
        'services_hero_subtitle': settings.get('servicios_hero_subtitulo'),
    }


def get_public_contact_destination_email():
    settings = get_brand_config()
    return settings.get('contacto_email_destino') or settings.get('empresa_email') or ''


def get_home_slides():
    return [
        {
            'imagen': item.get('image_url'),
            'titulo': item.get('title'),
            'descripcion': item.get('description'),
            'orden': item.get('sort_order') or 0,
        }
        for item in get_public_site_items('slide', include_inactive=False)
    ]


def get_home_publications():
    return [
        {
            'titulo': item.get('title'),
            'descripcion': item.get('description'),
            'imagen': item.get('image_url'),
        }
        for item in get_public_site_items('publication', include_inactive=False)
    ]


def get_home_services():
    return [
        {
            'titulo': item.get('title'),
            'descripcion': item.get('description'),
            'imagen': item.get('image_url'),
            'beneficios': item.get('extra_text'),
            'orden': item.get('sort_order') or 0,
        }
        for item in get_public_site_items('service', include_inactive=False)
    ]


def get_public_site_payload():
    return {
        'brand': get_brand_config(),
        'sections': get_public_sections(),
        'content': get_public_home_content(),
        'slides': get_home_slides(),
        'publications': get_home_publications(),
        'services': get_home_services(),
    }


def save_public_site_settings(form_data, keys):
    bootstrap_public_site_structure()

    for key in keys:
        if key in PUBLIC_LANDING_FIELD_TO_BLOCK:
            slug, target_field = PUBLIC_LANDING_FIELD_TO_BLOCK[key]
            block_values = _structured_blocks_map().get(slug, {})
            block_values[target_field] = (form_data.get(key) or '').strip()
            _upsert_public_block(
                slug,
                title=block_values.get('title'),
                body=block_values.get('body'),
                extra_body=block_values.get('extra_body'),
                subtitle=block_values.get('subtitle'),
                is_active=block_values.get('is_active', True),
                sort_order=block_values.get('sort_order', PUBLIC_BLOCK_DEFINITIONS[slug]['sort_order']),
            )
            _upsert_cliente_config(key, (form_data.get(key) or '').strip())
            continue

        if key not in PUBLIC_STRUCTURED_SETTING_BY_KEY:
            continue
        value = (form_data.get(key) or '').strip()
        _upsert_public_site_setting(key, value)
        _upsert_cliente_config(key, value)

    clear_public_site_cache()


def save_public_site_sections(form_data):
    bootstrap_public_site_structure()

    for field in PUBLIC_SECTION_FIELDS:
        enabled = bool(form_data.get(field['key']))
        _upsert_public_site_setting(field['key'], _bool_text(enabled))
        _upsert_config_seccion(field['key'], enabled)

    clear_public_site_cache()


def save_public_logo(file_storage, root_path):
    if not file_storage or not file_storage.filename:
        return None

    logo_url = _save_public_asset(file_storage, root_path, prefix='logo_publico')
    if not logo_url:
        return None

    bootstrap_public_site_structure()
    _upsert_public_site_setting('empresa_logo_url', logo_url)
    _upsert_cliente_config('empresa_logo_url', logo_url)
    clear_public_site_cache()
    return logo_url


def save_public_site_item(form_data, file_storage, root_path):
    bootstrap_public_site_structure()

    item_type = (form_data.get('item_type') or '').strip()
    if item_type not in PUBLIC_ITEM_TYPES:
        raise ValueError('Tipo de item publico no soportado.')

    item_id = _safe_int(form_data.get('item_id') or None, default=None)
    title = (form_data.get('title') or '').strip()
    subtitle = (form_data.get('subtitle') or '').strip()
    description = (form_data.get('description') or '').strip()
    cta_label = (form_data.get('cta_label') or '').strip()
    cta_url = (form_data.get('cta_url') or '').strip()
    extra_text = (form_data.get('extra_text') or '').strip()
    image_url = (form_data.get('current_image_url') or '').strip()
    sort_order = _safe_int(form_data.get('sort_order'), PUBLIC_ITEM_TYPES[item_type]['sort_default'])
    is_active = bool(form_data.get('is_active'))

    uploaded_image = _save_public_asset(file_storage, root_path, prefix=item_type)
    if uploaded_image:
        image_url = uploaded_image

    if item_id:
        with get_db_cursor() as cur:
            cur.execute(
                """
                UPDATE public_site_items
                SET title = %s,
                    subtitle = %s,
                    description = %s,
                    image_url = %s,
                    cta_label = %s,
                    cta_url = %s,
                    extra_text = %s,
                    sort_order = %s,
                    is_active = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND item_type = %s
                """,
                (
                    title,
                    subtitle,
                    description,
                    image_url,
                    cta_label,
                    cta_url,
                    extra_text,
                    sort_order,
                    is_active,
                    item_id,
                    item_type,
                ),
            )
    else:
        _create_public_site_item(
            item_type=item_type,
            title=title,
            subtitle=subtitle,
            description=description,
            image_url=image_url,
            cta_label=cta_label,
            cta_url=cta_url,
            extra_text=extra_text,
            sort_order=sort_order,
            is_active=is_active,
        )

    clear_public_site_cache()


def delete_public_site_item(item_id, item_type=None):
    bootstrap_public_site_structure()
    if not item_id:
        return

    with get_db_cursor() as cur:
        if item_type and item_type in PUBLIC_ITEM_TYPES:
            cur.execute('DELETE FROM public_site_items WHERE id = %s AND item_type = %s', (item_id, item_type))
        else:
            cur.execute('DELETE FROM public_site_items WHERE id = %s', (item_id,))
    clear_public_site_cache()


def toggle_public_site_item(item_id, item_type=None):
    bootstrap_public_site_structure()
    if not item_id:
        return

    with get_db_cursor() as cur:
        if item_type and item_type in PUBLIC_ITEM_TYPES:
            cur.execute(
                """
                UPDATE public_site_items
                SET is_active = NOT is_active,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND item_type = %s
                """,
                (item_id, item_type),
            )
        else:
            cur.execute(
                """
                UPDATE public_site_items
                SET is_active = NOT is_active,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (item_id,),
            )
    clear_public_site_cache()


def get_public_site_admin_context():
    bootstrap_public_site_structure()

    settings = get_public_site_settings()
    sections = get_public_sections()
    slides = get_public_site_items('slide', include_inactive=True)
    publications = get_public_site_items('publication', include_inactive=True)
    services = get_public_site_items('service', include_inactive=True)

    stats = {
        'slides': len(slides),
        'publications': len(publications),
        'services': len(services),
    }

    return {
        'public_site_settings': settings,
        'public_site_sections': sections,
        'branding_fields': PUBLIC_BRANDING_FIELDS,
        'color_fields': PUBLIC_COLOR_FIELDS,
        'landing_fields': PUBLIC_LANDING_FIELDS,
        'section_fields': PUBLIC_SECTION_FIELDS,
        'public_site_stats': stats,
        'public_site_items': {
            'slides': slides,
            'publications': publications,
            'services': services,
        },
        'public_item_types': PUBLIC_ITEM_TYPES,
        'public_site_preview': get_public_site_payload(),
    }
