-- =============================================================
-- Sitio Público unificado
-- Ejecutar en cada base de datos de cliente para preparar
-- branding, textos y visibilidad del frontend público.
-- =============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS config_secciones (
    clave       VARCHAR PRIMARY KEY,
    valor       TEXT NOT NULL DEFAULT 'true',
    descripcion TEXT
);

INSERT INTO config_secciones (clave, valor, descripcion)
SELECT 'mostrar_modulo_ventas', 'true', 'Muestra tienda, detalle de producto y carrito'
WHERE NOT EXISTS (SELECT 1 FROM config_secciones WHERE clave = 'mostrar_modulo_ventas');

INSERT INTO config_secciones (clave, valor, descripcion)
SELECT 'mostrar_about', 'true', 'Muestra el bloque quienes somos en el home'
WHERE NOT EXISTS (SELECT 1 FROM config_secciones WHERE clave = 'mostrar_about');

INSERT INTO config_secciones (clave, valor, descripcion)
SELECT 'mostrar_mision_vision', 'true', 'Muestra los bloques de misión y visión'
WHERE NOT EXISTS (SELECT 1 FROM config_secciones WHERE clave = 'mostrar_mision_vision');

INSERT INTO config_secciones (clave, valor, descripcion)
SELECT 'mostrar_publicaciones', 'true', 'Muestra publicaciones destacadas en el home'
WHERE NOT EXISTS (SELECT 1 FROM config_secciones WHERE clave = 'mostrar_publicaciones');

INSERT INTO config_secciones (clave, valor, descripcion)
SELECT 'mostrar_mapa', 'true', 'Muestra el mapa en la sección de contacto'
WHERE NOT EXISTS (SELECT 1 FROM config_secciones WHERE clave = 'mostrar_mapa');

INSERT INTO config_secciones (clave, valor, descripcion)
SELECT 'mostrar_contacto', 'true', 'Muestra el formulario de contacto'
WHERE NOT EXISTS (SELECT 1 FROM config_secciones WHERE clave = 'mostrar_contacto');

INSERT INTO config_secciones (clave, valor, descripcion)
SELECT 'mostrar_nav_productos', 'true', 'Muestra productos en el menú público'
WHERE NOT EXISTS (SELECT 1 FROM config_secciones WHERE clave = 'mostrar_nav_productos');

INSERT INTO config_secciones (clave, valor, descripcion)
SELECT 'mostrar_nav_servicios', 'true', 'Muestra servicios en el menú público'
WHERE NOT EXISTS (SELECT 1 FROM config_secciones WHERE clave = 'mostrar_nav_servicios');

INSERT INTO config_secciones (clave, valor, descripcion)
SELECT 'mostrar_nav_quienes_somos', 'true', 'Muestra quienes somos en el menú público'
WHERE NOT EXISTS (SELECT 1 FROM config_secciones WHERE clave = 'mostrar_nav_quienes_somos');

INSERT INTO config_secciones (clave, valor, descripcion)
SELECT 'mostrar_nav_contacto', 'true', 'Muestra contactanos en el menú público'
WHERE NOT EXISTS (SELECT 1 FROM config_secciones WHERE clave = 'mostrar_nav_contacto');

INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
SELECT 'empresa_tagline', 'Soluciones tecnológicas pensadas para crecer contigo.', 'text', 'sitio_publico', 'Mensaje corto de marca para el sitio público', 10
WHERE NOT EXISTS (SELECT 1 FROM cliente_config WHERE clave = 'empresa_tagline');

INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
SELECT 'contacto_email_destino', 'cybershop.digitalsales@gmail.com', 'email', 'sitio_publico', 'Correo destino del formulario de contacto', 11
WHERE NOT EXISTS (SELECT 1 FROM cliente_config WHERE clave = 'contacto_email_destino');

INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
SELECT 'empresa_logo_url', '/static/img/Logo.png', 'text', 'sitio_publico', 'Ruta del logo público', 12
WHERE NOT EXISTS (SELECT 1 FROM cliente_config WHERE clave = 'empresa_logo_url');

INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
SELECT 'home_about_title', '', 'text', 'sitio_publico', 'Título del bloque quienes somos', 20
WHERE NOT EXISTS (SELECT 1 FROM cliente_config WHERE clave = 'home_about_title');

INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
SELECT 'home_about_intro', 'Somos una empresa comprometida con la innovación y la excelencia tecnológica. Nuestro objetivo es ofrecer soluciones integrales que impulsen el desarrollo de nuestros clientes y optimicen sus operaciones. Nos destacamos por nuestra experiencia, dedicación y enfoque personalizado, siempre buscando superar expectativas.', 'text', 'sitio_publico', 'Primer párrafo del bloque quienes somos', 21
WHERE NOT EXISTS (SELECT 1 FROM cliente_config WHERE clave = 'home_about_intro');

INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
SELECT 'home_about_body', 'Con un equipo altamente capacitado y una visión orientada al futuro, trabajamos para convertirnos en tu aliado estratégico en tecnología. Transformamos desafíos en oportunidades, asegurándonos de que cada proyecto sea un éxito.', 'text', 'sitio_publico', 'Segundo párrafo del bloque quienes somos', 22
WHERE NOT EXISTS (SELECT 1 FROM cliente_config WHERE clave = 'home_about_body');

INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
SELECT 'home_mision_titulo', 'Misión', 'text', 'sitio_publico', 'Título del bloque misión', 23
WHERE NOT EXISTS (SELECT 1 FROM cliente_config WHERE clave = 'home_mision_titulo');

INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
SELECT 'home_mision_texto', 'Nos dedicamos a ofrecer soluciones tecnológicas integrales y personalizadas que impulsen el crecimiento y la eficiencia de nuestros clientes. A través de nuestra experiencia, dedicación y enfoque innovador, buscamos optimizar sus operaciones, superar expectativas y convertirnos en su aliado estratégico en el mundo digital.', 'text', 'sitio_publico', 'Contenido del bloque misión', 24
WHERE NOT EXISTS (SELECT 1 FROM cliente_config WHERE clave = 'home_mision_texto');

INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
SELECT 'home_vision_titulo', 'Visión', 'text', 'sitio_publico', 'Título del bloque visión', 25
WHERE NOT EXISTS (SELECT 1 FROM cliente_config WHERE clave = 'home_vision_titulo');

INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
SELECT 'home_vision_texto', 'Ser reconocidos como líderes en innovación y excelencia tecnológica, siendo el referente principal para empresas y personas que buscan soluciones confiables y vanguardistas. Aspiramos a construir un futuro donde la tecnología sea accesible, eficiente y transformadora.', 'text', 'sitio_publico', 'Contenido del bloque visión', 26
WHERE NOT EXISTS (SELECT 1 FROM cliente_config WHERE clave = 'home_vision_texto');

INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
SELECT 'home_publicaciones_titulo', 'Novedades', 'text', 'sitio_publico', 'Título del bloque de publicaciones', 27
WHERE NOT EXISTS (SELECT 1 FROM cliente_config WHERE clave = 'home_publicaciones_titulo');

INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
SELECT 'home_contacto_titulo', 'Contáctanos', 'text', 'sitio_publico', 'Título del formulario de contacto', 28
WHERE NOT EXISTS (SELECT 1 FROM cliente_config WHERE clave = 'home_contacto_titulo');

INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
SELECT 'home_contacto_intro', 'Cuéntanos lo que necesitas y nuestro equipo te responderá lo antes posible.', 'text', 'sitio_publico', 'Texto corto del bloque de contacto', 29
WHERE NOT EXISTS (SELECT 1 FROM cliente_config WHERE clave = 'home_contacto_intro');

INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
SELECT 'servicios_hero_titulo', 'Servicios', 'text', 'sitio_publico', 'Título de la página de servicios', 30
WHERE NOT EXISTS (SELECT 1 FROM cliente_config WHERE clave = 'servicios_hero_titulo');

INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
SELECT 'servicios_hero_subtitulo', 'Presentamos soluciones especializadas para operación, soporte y crecimiento digital.', 'text', 'sitio_publico', 'Subtítulo de la página de servicios', 31
WHERE NOT EXISTS (SELECT 1 FROM cliente_config WHERE clave = 'servicios_hero_subtitulo');

COMMIT;
