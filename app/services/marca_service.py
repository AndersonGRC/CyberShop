"""Paleta de marca a partir de UN color (prueba gratis y «Mi Negocio»).

El sitio público usa ~20 colores (PUBLIC_COLOR_FIELDS). Pedirle al dueño que
los elija uno a uno es lo que rompía el diseño (blanco sobre blanco). Aquí solo
elige su color principal y el resto se deriva con mezclas: tonos oscuros para
navbar/footer y hover, un tinte claro para los bloques destacados. Los acentos
de compra (verde «Añadir al carrito», naranja/rojo de etiquetas) se conservan.

`paleta_desde()` es una función pura: misma entrada, misma salida.
"""
import re

_HEX = re.compile(r'^#?([0-9a-fA-F]{6})$')

# Muestras del asistente y de Mi Negocio (todas con contraste ≥ 3 sobre blanco).
MUESTRAS = (
    ('#1e40af', 'Azul'), ('#0f766e', 'Verde azulado'), ('#15803d', 'Verde'),
    ('#b91c1c', 'Rojo'), ('#c2410c', 'Naranja'), ('#7e22ce', 'Morado'),
    ('#be185d', 'Fucsia'), ('#334155', 'Gris pizarra'),
)
NEUTRO = '#334155'          # sin color elegido: gris pizarra, ni el azul de CyberShop
CONTRASTE_MINIMO = 3.0      # texto blanco sobre el color (WCAG AA texto grande / botones)


def normalizar(color):
    """'#AbC123' → '#abc123'; None si no es un color #RRGGBB."""
    m = _HEX.match(str(color or '').strip())
    return f'#{m.group(1).lower()}' if m else None


def _rgb(color):
    c = normalizar(color)
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def _hex(rgb):
    return '#' + ''.join(f'{max(0, min(255, round(v))):02x}' for v in rgb)


def mezclar(color, otro, peso):
    """`peso` de `otro` sobre `color` (0 = color, 1 = otro)."""
    a, b = _rgb(color), _rgb(otro)
    return _hex(tuple(x + (y - x) * peso for x, y in zip(a, b)))


def _luminancia(color):
    def canal(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (canal(v) for v in _rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste_con_blanco(color):
    return 1.05 / (_luminancia(color) + 0.05)


def validar(color):
    """(color_normalizado, None) o (None, mensaje para la persona)."""
    c = normalizar(color)
    if not c:
        return None, 'Elige un color de la lista o escribe uno como #1e40af.'
    if contraste_con_blanco(c) < CONTRASTE_MINIMO:
        return None, ('Ese color es muy claro: los botones y títulos con texto blanco no se '
                      'leerían. Elige un tono más oscuro.')
    return c, None


def paleta_desde(color):
    """Claves de cliente_config del sitio público derivadas del color principal."""
    c = normalizar(color) or NEUTRO
    oscuro = mezclar(c, '#000000', 0.35)
    return {
        'color_primario': c,
        'color_primario_oscuro': oscuro,
        'color_botones': c,
        'color_producto_popup': c,
        'color_producto_boton': oscuro,
        'color_carrito': c,
        'color_carrito_hover': oscuro,
        'color_alerta_confirmar': c,
        'color_secundario': mezclar(c, '#0b1220', 0.78),     # navbar y footer
        'color_transicion': mezclar(c, '#000000', 0.55),     # 2.º tono del degradado
        'color_fondo_destacado': mezclar(c, '#ffffff', 0.92),  # bloques claros
    }


# ── Tienda nueva neutra (prueba gratis y compras en línea) ─────
LOGO_PROVISIONAL = '/static/img/tu-logo-aqui.svg'

_LEMAS = {
    'tienda': 'Productos de calidad, cerca de ti.',
    'restaurante': 'Sabor hecho con cariño, todos los días.',
    'servicios': 'Soluciones profesionales a tu medida.',
}


def valores_tienda_nueva(*, negocio, email, whatsapp, color=None, tipo=None, lema=None):
    """Lo que una tienda recién creada debe mostrar en vez de los datos de
    CyberShop: logo «Tu logo aquí», SUS datos de contacto, SU paleta y textos
    guía que invitan a editarlos desde Mi Negocio."""
    negocio = (negocio or 'Mi negocio').strip()
    valores = {
        'empresa_logo_url': LOGO_PROVISIONAL,
        'empresa_email': email,
        'contacto_email_destino': email,
        'empresa_copyright': negocio,
        'empresa_tagline': (lema or '').strip() or _LEMAS.get(tipo, 'Bienvenido a nuestra tienda en línea.'),
        'empresa_maps_embed': '',
        'home_about_intro': (f'{negocio}: cuéntale a tus clientes quiénes son y qué los hace '
                             'diferentes. Edita este texto en Mi Negocio.'),
        'home_about_body': ('Aquí puedes contar su historia, cómo empezaron y por qué sus '
                            'clientes los prefieren.'),
        'home_mision_texto': 'Escribe en Mi Negocio para qué existe tu negocio y a quién sirve.',
        'home_vision_texto': 'Escribe en Mi Negocio hacia dónde quieres llevar tu negocio.',
        'home_contacto_intro': 'Escríbenos y te responderemos lo antes posible.',
        'servicios_hero_subtitulo': 'Conoce lo que ofrecemos.',
    }
    if whatsapp:
        valores['empresa_telefono'] = whatsapp
        valores['empresa_whatsapp'] = '57' + whatsapp if len(whatsapp) == 10 else whatsapp
    valores.update(paleta_desde(color))
    return valores


def escribir_en_bd(cur, valores):
    """Escribe los valores en la BD del cliente (cursor de ESA BD): en
    cliente_config (tolerante, sin ON CONFLICT) y, si la tienda ya tiene la
    fila en public_site_settings (que se lee primero), también ahí."""
    from services.config_tenant import set_cliente_config
    from services.public_site_service import PUBLIC_FIELD_BY_KEY
    cur.execute("SELECT to_regclass('public_site_settings') IS NOT NULL AS hay")
    fila = cur.fetchone()
    hay_estructurada = bool(fila['hay'] if isinstance(fila, dict) else fila[0])
    for clave, valor in valores.items():
        campo = PUBLIC_FIELD_BY_KEY.get(clave) or {}
        set_cliente_config(cur, clave, valor, tipo=campo.get('type', 'text'),
                           grupo=campo.get('group', 'sitio_publico'),
                           descripcion=campo.get('description') or 'Tienda nueva (auto)')
        if hay_estructurada:
            cur.execute('UPDATE public_site_settings SET value = %s, updated_at = CURRENT_TIMESTAMP '
                        'WHERE key = %s', (valor, clave))
    # Textos de inicio: si la tienda ya tiene bloques estructurados, esos mandan.
    cur.execute("SELECT to_regclass('public_site_blocks') IS NOT NULL AS hay")
    fila = cur.fetchone()
    if not bool(fila['hay'] if isinstance(fila, dict) else fila[0]):
        return
    from services.public_site_service import PUBLIC_BLOCK_DEFINITIONS
    for slug, definicion in PUBLIC_BLOCK_DEFINITIONS.items():
        for columna, llave in (('title', definicion.get('title_key')), ('body', definicion.get('body_key')),
                               ('extra_body', definicion.get('extra_body_key'))):
            if llave and llave in valores:
                cur.execute(f'UPDATE public_site_blocks SET {columna} = %s WHERE slug = %s',
                            (valores[llave], slug))
