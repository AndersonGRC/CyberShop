-- =============================================================
-- Sitio Público estructurado por cliente
-- Crea tablas propias del módulo y migra datos desde
-- cliente_config, config_secciones, slides_home,
-- publicaciones_home y servicios_home si existen.
-- =============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public_site_settings (
    key         VARCHAR PRIMARY KEY,
    value       TEXT,
    value_type  VARCHAR NOT NULL DEFAULT 'text',
    group_name  VARCHAR NOT NULL DEFAULT 'general',
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

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
);

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
);

CREATE INDEX IF NOT EXISTS idx_public_site_settings_group
    ON public_site_settings(group_name, sort_order);

CREATE INDEX IF NOT EXISTS idx_public_site_blocks_type
    ON public_site_blocks(block_type, sort_order);

CREATE INDEX IF NOT EXISTS idx_public_site_items_type
    ON public_site_items(item_type, sort_order, is_active);

INSERT INTO public_site_settings (key, value, value_type, group_name, description, sort_order)
VALUES
    ('empresa_nombre', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'empresa_nombre'), 'CyberShop'), 'text', 'empresa', 'Nombre visible del sitio y de la empresa.', 1),
    ('empresa_tagline', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'empresa_tagline'), 'Soluciones tecnológicas pensadas para crecer contigo.'), 'text', 'sitio_publico', 'Texto breve usado en el pie de pagina del sitio publico.', 10),
    ('empresa_email', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'empresa_email'), 'cybershop.digitalsales@gmail.com'), 'email', 'empresa', 'Correo visible para clientes y formularios.', 2),
    ('contacto_email_destino', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'contacto_email_destino'), 'cybershop.digitalsales@gmail.com'), 'email', 'sitio_publico', 'Destino interno de los mensajes enviados desde el home.', 11),
    ('empresa_telefono', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'empresa_telefono'), '3015963776'), 'tel', 'empresa', 'Telefono visible en la comunicacion publica.', 3),
    ('empresa_whatsapp', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'empresa_whatsapp'), '573027974969'), 'text', 'empresa', 'Numero en formato internacional para el boton flotante.', 4),
    ('empresa_direccion', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'empresa_direccion'), ''), 'text', 'empresa', 'Direccion visible para clientes.', 5),
    ('empresa_website', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'empresa_website'), ''), 'url', 'empresa', 'URL oficial mostrable en documentos y secciones de contacto.', 6),
    ('empresa_maps_embed', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'empresa_maps_embed'), 'https://www.google.com/maps/embed?pb=!1m18!1m12!1m3!1d3976.1438661161997!2d-74.12405722491505!3d4.7450433952301445!2m3!1f0!2f0!3f0!3m2!1i1024!2i768!4f13.1!3m3!1m2!1s0x8e3f8481ac8fae15%3A0xd086f2615f6ea83!2sCra.%20151%20%23136a11%2C%20Suba%2C%20Bogot%C3%A1!5e0!3m2!1ses!2sco!4v1737344695200!5m2!1ses!2sco'), 'url', 'empresa', 'URL completa del mapa embebido de Google Maps.', 7),
    ('empresa_facebook', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'empresa_facebook'), '#'), 'url', 'empresa', 'URL de la red social.', 8),
    ('empresa_instagram', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'empresa_instagram'), '#'), 'url', 'empresa', 'URL de la red social.', 9),
    ('empresa_linkedin', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'empresa_linkedin'), '#'), 'url', 'empresa', 'URL de la red social.', 10),
    ('empresa_youtube', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'empresa_youtube'), '#'), 'url', 'empresa', 'URL de la red social.', 11),
    ('empresa_twitter', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'empresa_twitter'), '#'), 'url', 'empresa', 'URL de la red social.', 12),
    ('empresa_copyright', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'empresa_copyright'), COALESCE((SELECT valor FROM cliente_config WHERE clave = 'empresa_nombre'), 'CyberShop')), 'text', 'empresa', 'Texto visible en footer y plantillas.', 13),
    ('empresa_logo_url', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'empresa_logo_url'), '/static/img/Logo.png'), 'text', 'sitio_publico', 'Ruta del logo publico.', 12),
    ('color_secundario', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'color_secundario'), '#0e1b33'), 'color', 'colores', 'Color del sistema publico.', 101),
    ('color_transicion', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'color_transicion'), '#16315f'), 'color', 'colores', 'Color del sistema publico.', 102),
    ('color_fondo_destacado', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'color_fondo_destacado'), '#edf3ff'), 'color', 'colores', 'Color del sistema publico.', 103),
    ('color_primario', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'color_primario'), '#122C94'), 'color', 'colores', 'Color del sistema publico.', 104),
    ('color_primario_oscuro', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'color_primario_oscuro'), '#091C5A'), 'color', 'colores', 'Color del sistema publico.', 105),
    ('color_botones', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'color_botones'), '#122C94'), 'color', 'colores', 'Color del sistema publico.', 106),
    ('color_acento', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'color_acento'), '#e60023'), 'color', 'colores', 'Color del sistema publico.', 107),
    ('color_acento_secundario', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'color_acento_secundario'), '#fb8500'), 'color', 'colores', 'Color del sistema publico.', 108),
    ('color_hover_menu', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'color_hover_menu'), '#fb8500'), 'color', 'colores', 'Color del sistema publico.', 109),
    ('color_carrito', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'color_carrito'), '#122C94'), 'color', 'colores', 'Color del sistema publico.', 110),
    ('color_carrito_hover', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'color_carrito_hover'), '#091C5A'), 'color', 'colores', 'Color del sistema publico.', 111),
    ('color_producto_boton', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'color_producto_boton'), '#091C5A'), 'color', 'colores', 'Color del sistema publico.', 112),
    ('color_producto_popup', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'color_producto_popup'), '#122C94'), 'color', 'colores', 'Color del sistema publico.', 113),
    ('color_alerta_fondo', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'color_alerta_fondo'), '#ffffff'), 'color', 'colores', 'Color del sistema publico.', 114),
    ('color_alerta_texto', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'color_alerta_texto'), '#333333'), 'color', 'colores', 'Color del sistema publico.', 115),
    ('color_alerta_confirmar', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'color_alerta_confirmar'), '#122C94'), 'color', 'colores', 'Color del sistema publico.', 116),
    ('color_alerta_cancelar', COALESCE((SELECT valor FROM cliente_config WHERE clave = 'color_alerta_cancelar'), '#dc3545'), 'color', 'colores', 'Color del sistema publico.', 117),
    ('mostrar_modulo_ventas', COALESCE((SELECT valor FROM config_secciones WHERE clave = 'mostrar_modulo_ventas'), 'true'), 'boolean', 'sitio_publico_secciones', 'Muestra productos, detalle de producto, carrito y accesos de compra.', 301),
    ('mostrar_about', COALESCE((SELECT valor FROM config_secciones WHERE clave = 'mostrar_about'), 'true'), 'boolean', 'sitio_publico_secciones', 'Muestra la seccion descriptiva principal del home.', 302),
    ('mostrar_mision_vision', COALESCE((SELECT valor FROM config_secciones WHERE clave = 'mostrar_mision_vision'), 'true'), 'boolean', 'sitio_publico_secciones', 'Activa los bloques institucionales de mision y vision.', 303),
    ('mostrar_publicaciones', COALESCE((SELECT valor FROM config_secciones WHERE clave = 'mostrar_publicaciones'), 'true'), 'boolean', 'sitio_publico_secciones', 'Muestra las publicaciones destacadas del inicio.', 304),
    ('mostrar_mapa', COALESCE((SELECT valor FROM config_secciones WHERE clave = 'mostrar_mapa'), 'true'), 'boolean', 'sitio_publico_secciones', 'Activa el mapa embebido en la seccion de contacto.', 305),
    ('mostrar_contacto', COALESCE((SELECT valor FROM config_secciones WHERE clave = 'mostrar_contacto'), 'true'), 'boolean', 'sitio_publico_secciones', 'Muestra el formulario de contacto del home.', 306),
    ('mostrar_nav_productos', COALESCE((SELECT valor FROM config_secciones WHERE clave = 'mostrar_nav_productos'), 'true'), 'boolean', 'sitio_publico_secciones', 'Muestra el acceso a productos en el menu superior.', 307),
    ('mostrar_nav_servicios', COALESCE((SELECT valor FROM config_secciones WHERE clave = 'mostrar_nav_servicios'), 'true'), 'boolean', 'sitio_publico_secciones', 'Muestra el acceso a servicios en el menu superior.', 308),
    ('mostrar_nav_quienes_somos', COALESCE((SELECT valor FROM config_secciones WHERE clave = 'mostrar_nav_quienes_somos'), 'true'), 'boolean', 'sitio_publico_secciones', 'Muestra el acceso rapido a la seccion institucional.', 309),
    ('mostrar_nav_contacto', COALESCE((SELECT valor FROM config_secciones WHERE clave = 'mostrar_nav_contacto'), 'true'), 'boolean', 'sitio_publico_secciones', 'Muestra el acceso rapido a la seccion de contacto.', 310)
ON CONFLICT (key) DO NOTHING;

INSERT INTO public_site_blocks (slug, block_type, title, subtitle, body, extra_body, sort_order, is_active)
VALUES
    ('about', 'landing',
        COALESCE((SELECT valor FROM cliente_config WHERE clave = 'home_about_title'), ''),
        '',
        COALESCE((SELECT valor FROM cliente_config WHERE clave = 'home_about_intro'), 'Somos una empresa comprometida con la innovación y la excelencia tecnológica. Nuestro objetivo es ofrecer soluciones integrales que impulsen el desarrollo de nuestros clientes y optimicen sus operaciones.'),
        COALESCE((SELECT valor FROM cliente_config WHERE clave = 'home_about_body'), 'Con un equipo altamente capacitado y una visión orientada al futuro, trabajamos para convertirnos en tu aliado estratégico en tecnología.'),
        10, TRUE),
    ('mission', 'landing',
        COALESCE((SELECT valor FROM cliente_config WHERE clave = 'home_mision_titulo'), 'Misión'),
        '',
        COALESCE((SELECT valor FROM cliente_config WHERE clave = 'home_mision_texto'), 'Nos dedicamos a ofrecer soluciones tecnológicas integrales y personalizadas que impulsen el crecimiento y la eficiencia de nuestros clientes.'),
        '',
        20, TRUE),
    ('vision', 'landing',
        COALESCE((SELECT valor FROM cliente_config WHERE clave = 'home_vision_titulo'), 'Visión'),
        '',
        COALESCE((SELECT valor FROM cliente_config WHERE clave = 'home_vision_texto'), 'Ser reconocidos como líderes en innovación y excelencia tecnológica.'),
        '',
        30, TRUE),
    ('publications', 'landing',
        COALESCE((SELECT valor FROM cliente_config WHERE clave = 'home_publicaciones_titulo'), 'Novedades'),
        '',
        '',
        '',
        40, TRUE),
    ('contact', 'landing',
        COALESCE((SELECT valor FROM cliente_config WHERE clave = 'home_contacto_titulo'), 'Contáctanos'),
        '',
        COALESCE((SELECT valor FROM cliente_config WHERE clave = 'home_contacto_intro'), 'Cuéntanos lo que necesitas y nuestro equipo te responderá lo antes posible.'),
        '',
        50, TRUE),
    ('services_hero', 'landing',
        COALESCE((SELECT valor FROM cliente_config WHERE clave = 'servicios_hero_titulo'), 'Servicios'),
        '',
        COALESCE((SELECT valor FROM cliente_config WHERE clave = 'servicios_hero_subtitulo'), 'Presentamos soluciones especializadas para operación, soporte y crecimiento digital.'),
        '',
        60, TRUE)
ON CONFLICT (slug) DO NOTHING;

DO $$
BEGIN
    IF to_regclass('public.slides_home') IS NOT NULL THEN
        INSERT INTO public_site_items (item_type, title, description, image_url, sort_order, is_active, created_at, updated_at)
        SELECT 'slide', s.titulo, s.descripcion, s.imagen, COALESCE(s.orden, 0), COALESCE(s.activo, TRUE), CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM slides_home s
        WHERE NOT EXISTS (
            SELECT 1 FROM public_site_items psi WHERE psi.item_type = 'slide'
        );
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('public.publicaciones_home') IS NOT NULL THEN
        INSERT INTO public_site_items (item_type, title, description, image_url, sort_order, is_active, created_at, updated_at)
        SELECT 'publication', p.titulo, p.descripcion, p.imagen, 0, COALESCE(p.activo, TRUE), CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM publicaciones_home p
        WHERE NOT EXISTS (
            SELECT 1 FROM public_site_items psi WHERE psi.item_type = 'publication'
        );
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('public.servicios_home') IS NOT NULL THEN
        INSERT INTO public_site_items (item_type, title, description, image_url, extra_text, sort_order, is_active, created_at, updated_at)
        SELECT 'service', s.titulo, s.descripcion, s.imagen, s.beneficios, COALESCE(s.orden, 0), COALESCE(s.activo, TRUE), CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM servicios_home s
        WHERE NOT EXISTS (
            SELECT 1 FROM public_site_items psi WHERE psi.item_type = 'service'
        );
    END IF;
END $$;

COMMIT;
