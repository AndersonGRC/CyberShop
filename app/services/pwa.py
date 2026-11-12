# -*- coding: utf-8 -*-
"""services/pwa.py — La tienda y el panel se instalan como una app (PWA, 1.9.20.0).

Cada tienda sale con SU nombre, SU color y SU logo: nada se comparte entre tiendas
y nada se guarda en disco (los íconos se dibujan en memoria a partir del logo).

Se apaga por tienda con `PWA_ACTIVA=0` en su `.env`: las páginas dejan de ofrecer
la instalación y `/sw.js` entrega un service worker que se retira solo.
"""
import hashlib
import io
import os
import re

from flask import current_app

COLOR_PANEL = '#122C94'          # el panel usa la paleta de CyberShop en todas las tiendas
TAMANOS = (180, 192, 512)
VARIANTES = ('normal', 'maskable')
# Cuánto del cuadro ocupa el logo. «maskable»: el sistema recorta el ícono en
# círculo, así que el logo va más pequeño para quedar dentro de la zona segura.
_OCUPA = {'normal': 0.78, 'maskable': 0.56}

_HEX = re.compile(r'^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')
_iconos = {}                     # (base, logo, mtime, color, letra, variante, tamaño) -> PNG


def activa():
    return (os.getenv('PWA_ACTIVA', '1') or '1').strip().lower() not in ('0', 'false', 'no')


def color_hex(valor, defecto=COLOR_PANEL):
    valor = (valor or '').strip()
    return valor if _HEX.match(valor) else defecto


def nombre_corto(nombre, largo=12):
    """Nombre para debajo del ícono: entero si cabe; si no, las primeras palabras."""
    nombre = ' '.join((nombre or '').split())
    if len(nombre) <= largo:
        return nombre
    corto = ''
    for palabra in nombre.split(' '):
        candidato = (corto + ' ' + palabra).strip()
        if len(candidato) > largo:
            break
        corto = candidato
    return corto or nombre[:largo]


def _marca():
    from services.public_site_service import get_brand_config
    try:
        return get_brand_config() or {}
    except Exception as exc:  # noqa: BLE001 — sin marca, la app sale con lo básico
        current_app.logger.warning(f"PWA: no se pudo leer la marca: {exc}")
        return {}


def _nombre(marca):
    return ' '.join((marca.get('empresa_nombre') or '').split()) or 'Mi tienda'


def _logo_local(marca):
    """Archivo del logo de ESTA tienda, o None si no hay uno que se pueda dibujar
    (sin logo propio, SVG, archivo perdido). Primero la carpeta propia de la tienda."""
    url = (marca.get('empresa_logo_url') or '').split('?')[0]
    if not url.startswith('/static/'):
        return None
    relativo = url[len('/static/'):]
    if '..' in relativo.replace('\\', '/').split('/'):
        return None
    propia = (current_app.config.get('INSTANCE_OVERRIDES_DIR') or '').strip()
    carpetas = ([os.path.join(propia, 'static')] if propia else []) + [current_app.static_folder]
    nombres = [relativo]
    if relativo.lower() == 'img/logo.png':       # en el servidor el archivo es Logo.PNG
        nombres = ['img/Logo.png', 'img/Logo.PNG']
    for carpeta in carpetas:
        for nombre in nombres:
            ruta = os.path.join(carpeta, *nombre.split('/'))
            if os.path.isfile(ruta):
                if carpeta == current_app.static_folder and relativo.lower() == 'img/logo.png' \
                        and not _es_operador():
                    return None                  # es el logo de CyberShop, no el de esta tienda
                return ruta
    return None


def _es_operador():
    try:
        from services.public_site_service import _es_operador as operador
        return operador() is not False
    except Exception:  # noqa: BLE001
        return True


def _datos_icono():
    marca = _marca()
    ruta = _logo_local(marca)
    try:
        mtime = int(os.path.getmtime(ruta)) if ruta else 0
    except OSError:
        ruta, mtime = None, 0
    from database import _current_db_name
    return {
        'base': _current_db_name() or '',
        'logo': ruta or '',
        'mtime': mtime,
        'color': color_hex(marca.get('color_primario')),
        'letra': (_nombre(marca)[:1] or 'T').upper(),
    }


def version_icono():
    """Cambia cuando cambia el logo, el color o el nombre: así el teléfono actualiza
    el ícono de la app ya instalada."""
    d = _datos_icono()
    crudo = '|'.join(str(d[k]) for k in ('base', 'logo', 'mtime', 'color', 'letra'))
    return hashlib.sha1(crudo.encode('utf-8')).hexdigest()[:10]


def _rgb(color):
    c = color.lstrip('#')
    if len(c) == 3:
        c = ''.join(ch * 2 for ch in c)
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _es_claro(rgb):
    return (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) > 170


def _dibujar_logo(ruta, color, variante, tamano):
    from PIL import Image
    with Image.open(ruta) as original:
        logo = original.convert('RGBA')
    caja = logo.getbbox()                        # sin los bordes transparentes
    if caja:
        logo = logo.crop(caja)
    # Fondo blanco; si el logo es claro (pensado para fondo oscuro), el color de la tienda.
    crudo = logo.resize((32, 32)).tobytes()      # RGBA de corrido (sirve en cualquier Pillow)
    visibles = [crudo[i:i + 4] for i in range(0, len(crudo), 4) if crudo[i + 3] > 40]
    fondo = (255, 255, 255)
    if visibles:
        medio = tuple(sum(p[i] for p in visibles) // len(visibles) for i in range(3))
        if _es_claro(medio):
            fondo = _rgb(color)
            if _es_claro(fondo):
                fondo = _rgb(COLOR_PANEL)
    lado = max(1, int(tamano * _OCUPA[variante]))
    escala = min(lado / logo.width, lado / logo.height)
    logo = logo.resize((max(1, round(logo.width * escala)), max(1, round(logo.height * escala))),
                       Image.LANCZOS)
    lienzo = Image.new('RGBA', (tamano, tamano), fondo + (255,))
    lienzo.alpha_composite(logo, ((tamano - logo.width) // 2, (tamano - logo.height) // 2))
    return lienzo.convert('RGB')


def _dibujar_letra(letra, color, tamano):
    """Sin logo propio: la inicial de la tienda sobre su color."""
    from PIL import Image, ImageDraw, ImageFont
    fondo = _rgb(color)
    tinta = (31, 41, 51) if _es_claro(fondo) else (255, 255, 255)
    lienzo = Image.new('RGB', (tamano, tamano), fondo)
    try:
        fuente = ImageFont.load_default(size=int(tamano * 0.5))
        ImageDraw.Draw(lienzo).text((tamano / 2, tamano / 2), letra, font=fuente, fill=tinta, anchor='mm')
    except Exception:  # noqa: BLE001 — sin fuente escalable queda el cuadro de color
        pass
    return lienzo


def icono_png(tamano, variante='normal'):
    """El ícono de esta tienda en PNG. Se dibuja una vez y queda en memoria."""
    if tamano not in TAMANOS or variante not in VARIANTES:
        return None
    d = _datos_icono()
    llave = (d['base'], d['logo'], d['mtime'], d['color'], d['letra'], variante, tamano)
    if llave in _iconos:
        return _iconos[llave]
    imagen = None
    if d['logo']:
        try:
            imagen = _dibujar_logo(d['logo'], d['color'], variante, tamano)
        except Exception as exc:  # noqa: BLE001 — logo dañado o formato raro: la inicial
            current_app.logger.warning(f"PWA: no se pudo dibujar el logo: {exc}")
    if imagen is None:
        imagen = _dibujar_letra(d['letra'], d['color'], tamano)
    salida = io.BytesIO()
    imagen.save(salida, format='PNG', optimize=True)
    if len(_iconos) > 60:
        _iconos.clear()
    _iconos[llave] = salida.getvalue()
    return _iconos[llave]


def _lista_iconos():
    v = version_icono()
    return [
        {'src': f'/pwa/icono-192.png?v={v}', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
        {'src': f'/pwa/icono-512.png?v={v}', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
        {'src': f'/pwa/icono-maskable-192.png?v={v}', 'sizes': '192x192', 'type': 'image/png',
         'purpose': 'maskable'},
        {'src': f'/pwa/icono-maskable-512.png?v={v}', 'sizes': '512x512', 'type': 'image/png',
         'purpose': 'maskable'},
    ]


def manifiesto(tipo='tienda'):
    """El «manifiesto» que el teléfono lee para instalar. `tipo`: 'tienda' (la página
    que ven los compradores) o 'panel' (donde trabaja el negocio)."""
    marca = _marca()
    nombre = _nombre(marca)
    base = {'lang': 'es', 'dir': 'ltr', 'scope': '/', 'display': 'standalone',
            'orientation': 'any', 'background_color': '#ffffff', 'icons': _lista_iconos()}
    if tipo == 'panel':
        base.update({
            'id': '/pwa/panel',
            'name': f'Panel {nombre}',
            'short_name': nombre_corto(f'Panel {nombre}', 16),
            'description': f'Panel de administración de {nombre}.',
            'start_url': '/pwa/panel',
            'theme_color': COLOR_PANEL,
        })
    else:
        base.update({
            'id': '/',
            'name': nombre,
            'short_name': nombre_corto(nombre),
            'description': (marca.get('empresa_tagline') or '').strip() or f'Tienda en línea de {nombre}.',
            'start_url': '/',
            'theme_color': color_hex(marca.get('color_primario')),
        })
    return base


def pagina_sin_conexion():
    """Lo único que la app guarda en el equipo: el aviso de «sin internet»."""
    marca = _marca()
    from markupsafe import escape
    nombre = escape(_nombre(marca))
    color = color_hex(marca.get('color_primario'))
    if _es_claro(_rgb(color)):
        color = COLOR_PANEL
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex, nofollow">'
        f'<meta name="theme-color" content="{color}">'
        f'<title>Sin conexión · {nombre}</title></head>'
        '<body style="margin:0;font-family:system-ui,Segoe UI,Arial,sans-serif;background:#f4f5f7;color:#1f2933">'
        '<div style="padding:0 16px"><div style="max-width:420px;margin:16vh auto 0;padding:30px 24px;'
        'box-sizing:border-box;background:#fff;'
        'border-radius:16px;box-shadow:0 6px 24px rgba(0,0,0,.08);text-align:center">'
        '<img src="/pwa/icono-192.png" alt="" width="84" height="84" style="border-radius:20px" '
        'onerror="this.remove()">'
        '<h1 style="font-size:1.3rem;margin:16px 0 8px">No hay conexión a internet</h1>'
        f'<p style="margin:0 0 22px;line-height:1.5;color:#52606d">{nombre} se abrirá sola '
        'apenas vuelva la conexión.</p>'
        f'<button type="button" onclick="location.reload()" style="background:{color};color:#fff;'
        'border:0;border-radius:11px;padding:13px 26px;font-size:1rem;font-weight:700;cursor:pointer">'
        'Reintentar</button></div></div>'
        '<script>window.addEventListener("online",function(){location.reload()});</script>'
        '</body></html>'
    )


def service_worker(version):
    """Service worker mínimo a propósito: NO guarda páginas, datos ni nada del panel.
    Solo muestra el aviso de «sin conexión» cuando una página no carga por falta de red."""
    if not activa():
        return (
            "/* CyberShop: app instalable apagada en esta tienda; este archivo se retira solo. */\n"
            "self.addEventListener('install', function () { self.skipWaiting(); });\n"
            "self.addEventListener('activate', function (e) {\n"
            "  e.waitUntil(caches.keys().then(function (ks) {\n"
            "    return Promise.all(ks.filter(function (k) { return k.indexOf('cs-pwa-') === 0; })\n"
            "      .map(function (k) { return caches.delete(k); }));\n"
            "  }).then(function () { return self.registration.unregister(); }));\n"
            "});\n"
        )
    return (
        "/* CyberShop " + version + ": solo el aviso de «sin conexión». Nada más se guarda. */\n"
        "var CACHE = 'cs-pwa-" + version + "';\n"
        "var AVISO = '/pwa/sin-conexion';\n"
        "self.addEventListener('install', function (e) {\n"
        "  e.waitUntil(caches.open(CACHE).then(function (c) {\n"
        "    return c.addAll([new Request(AVISO, {cache: 'reload'}),\n"
        "                     new Request('/pwa/icono-192.png', {cache: 'reload'})]);\n"
        "  }).then(function () { return self.skipWaiting(); }));\n"
        "});\n"
        "self.addEventListener('activate', function (e) {\n"
        "  e.waitUntil(caches.keys().then(function (ks) {\n"
        "    return Promise.all(ks.filter(function (k) { return k.indexOf('cs-pwa-') === 0 && k !== CACHE; })\n"
        "      .map(function (k) { return caches.delete(k); }));\n"
        "  }).then(function () { return self.clients.claim(); }));\n"
        "});\n"
        "self.addEventListener('fetch', function (e) {\n"
        "  var r = e.request;\n"
        "  if (r.method !== 'GET') { return; }\n"
        "  if (r.mode === 'navigate') {\n"
        "    e.respondWith(fetch(r).catch(function () {\n"
        "      return caches.match(AVISO).then(function (p) { return p || Response.error(); });\n"
        "    }));\n"
        "    return;\n"
        "  }\n"
        "  if (new URL(r.url).pathname === '/pwa/icono-192.png') {\n"
        "    e.respondWith(fetch(r).catch(function () {\n"
        "      return caches.match('/pwa/icono-192.png').then(function (p) { return p || Response.error(); });\n"
        "    }));\n"
        "  }\n"
        "});\n"
    )
