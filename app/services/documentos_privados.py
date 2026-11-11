# -*- coding: utf-8 -*-
"""Cotizaciones y cuentas de cobro en PDF: de cada tienda y nunca públicas (1.9.19.0).

Antes el PDF se guardaba en `static/` del código compartido: cualquiera lo abría sin
iniciar sesión y todas las tiendas veían el mismo archivo (`Cotizacion_12.pdf` de una
tapaba el de otra). Ahora:

- El PDF NO se guarda: se arma con los datos de la tienda cada vez que se pide, así
  siempre es el de esa tienda y refleja lo que hay guardado.
- En el panel se abre con la sesión (`/admin/cotizar/<id>/pdf`, `/admin/cuenta_cobro/<id>/pdf`).
- Al cliente se le manda un enlace privado (`/doc/<token>`): firmado con la llave de
  la tienda Y el nombre de su base (un enlace de una tienda no abre nada en otra,
  aunque compartan la llave), y vence a los 30 días.
- Las dos carpetas públicas viejas dejan de servirse, y lo que había se MUEVE (no se
  borra) a una carpeta cerrada: `uploads/archivo_pdf_publicos/`.
"""
import os
import posixpath
import re
import time
from io import BytesIO
from urllib.parse import quote

from flask import current_app, send_file, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

ENLACE_DIAS = 30

# tipo → (letra del enlace, tabla, nombre del archivo que se descarga)
TIPOS = {
    'cotizacion':   ('c', 'cotizaciones',  'Cotizacion_{id}.pdf'),
    'cuenta_cobro': ('q', 'cuentas_cobro', 'CueCob_{id}.pdf'),
}
_TIPO_POR_LETRA = {letra: tipo for tipo, (letra, _, _) in TIPOS.items()}

# Carpetas de `static/` donde quedaban los PDF. Ya no se sirven ni se escriben.
CARPETAS_CERRADAS = ('cotizaciones/pdf', 'cuentas_cobro/pdf')
CARPETA_ARCHIVO = ('uploads', 'archivo_pdf_publicos')


# ── Enlace privado para el cliente ──────────────────────────────
def _firmador():
    from database import _current_db_name
    return URLSafeTimedSerializer(current_app.secret_key,
                                  salt=f'doc-publico:{_current_db_name()}')


def firmar(tipo, doc_id):
    """Token del enlace privado de ese documento de ESTA tienda."""
    return _firmador().dumps([TIPOS[tipo][0], int(doc_id)])


def leer_token(token):
    """(tipo, id, estado). estado: 'ok', 'vencido' (pasaron los 30 días) o 'invalido'
    (alterado, de otra tienda o mal escrito)."""
    try:
        letra, doc_id = _firmador().loads(token, max_age=ENLACE_DIAS * 86400)
        return _TIPO_POR_LETRA[letra], int(doc_id), 'ok'
    except SignatureExpired:
        return None, None, 'vencido'
    except (BadSignature, KeyError, TypeError, ValueError):
        return None, None, 'invalido'


def enlace(tipo, doc_id):
    """Dirección completa que se le manda al cliente; '' si no se puede armar."""
    try:
        return url_for('documentos.ver', token=firmar(tipo, doc_id), _external=True)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f"Enlace privado de {tipo} {doc_id}: {exc}")
        return ''


def celular_whatsapp(telefono):
    """El celular como lo pide WhatsApp (57 + 10 dígitos); '' si no es un celular
    colombiano reconocible (entonces WhatsApp deja escoger el contacto)."""
    digitos = re.sub(r'\D', '', str(telefono or ''))
    if len(digitos) == 12 and digitos.startswith('573'):
        return digitos
    if len(digitos) == 10 and digitos.startswith('3'):
        return '57' + digitos
    return ''


def enlace_whatsapp(telefono, mensaje):
    return f"https://wa.me/{celular_whatsapp(telefono)}?text={quote(mensaje, safe='')}"


def preparar_filas(tipo, filas, mensaje):
    """Devuelve las filas de la lista (como diccionarios: las de la base no dejan
    agregar campos) con lo que usa la pantalla: `pdf_privado` (el botón PDF abre la
    ruta con sesión), `enlace` (para copiar) y `wa` (WhatsApp con el mensaje listo).
    `mensaje(fila, enlace)` devuelve el texto. Nunca frena la lista: si algo falla,
    esa fila sale tal como venía."""
    listas = []
    for original in filas or []:
        try:
            fila = dict(original)
            fila['pdf_privado'] = True
            fila['enlace'] = enlace(tipo, fila['id'])
            if fila['enlace']:
                fila['wa'] = enlace_whatsapp(fila.get('cliente_telefono'),
                                             mensaje(fila, fila['enlace']))
            listas.append(fila)
        except Exception as exc:  # noqa: BLE001
            current_app.logger.warning(f"Enlaces de {tipo}: {exc}")
            listas.append(original)
    return listas


# ── El PDF ──────────────────────────────────────────────────────
def pdf_de(tipo, doc_id):
    """El PDF (bytes) de ese documento de la tienda actual, armado con lo que hay en
    su base; None si no existe o no se pudo armar."""
    try:
        if tipo == 'cotizacion':
            from routes.quotes import pdf_cotizacion_desde_bd
            return pdf_cotizacion_desde_bd(doc_id)
        if tipo == 'cuenta_cobro':
            from routes.billing import pdf_cuenta_desde_bd
            return pdf_cuenta_desde_bd(doc_id)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error(f"PDF de {tipo} {doc_id}: {exc}")
    return None


def nombre_archivo(tipo, doc_id):
    return TIPOS[tipo][2].format(id=int(doc_id))


def respuesta_pdf(contenido, nombre, descargar=False):
    """El PDF para el navegador: privado, sin caché y sin buscadores."""
    respuesta = send_file(BytesIO(contenido), mimetype='application/pdf',
                          as_attachment=descargar, download_name=nombre)
    respuesta.headers['Cache-Control'] = 'private, no-store, max-age=0'
    respuesta.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return respuesta


# ── Las carpetas públicas viejas ────────────────────────────────
def es_carpeta_cerrada(filename):
    """¿Ese archivo de /static está en una de las carpetas de PDF que ya no se sirven?
    Se compara ya normalizado (`x/../cotizaciones/pdf/a.pdf` también cuenta)."""
    limpio = posixpath.normpath(str(filename or '').replace('\\', '/')).lstrip('/').lower()
    return any(limpio == carpeta or limpio.startswith(carpeta + '/') for carpeta in CARPETAS_CERRADAS)


def archivar_pdf_publicos(root_path, logger=None):
    """Saca de `static/` los PDF que quedaron públicos y los deja en
    `uploads/archivo_pdf_publicos/` (fuera de lo que se sirve). NO borra nada: si en
    el archivo ya hay uno con ese nombre, el nuevo queda con la hora en el nombre.
    Devuelve cuántos movió. Varias instancias pueden correrlo a la vez."""
    movidos = 0
    for carpeta in CARPETAS_CERRADAS:
        origen = os.path.join(root_path, 'static', *carpeta.split('/'))
        if not os.path.isdir(origen):
            continue
        destino = os.path.join(root_path, *CARPETA_ARCHIVO, carpeta.split('/')[0])
        try:
            nombres = os.listdir(origen)
        except OSError:
            continue
        for nombre in nombres:
            archivo = os.path.join(origen, nombre)
            if not os.path.isfile(archivo):
                continue
            try:
                os.makedirs(destino, exist_ok=True)
                final = os.path.join(destino, nombre)
                if os.path.exists(final):
                    base, ext = os.path.splitext(nombre)
                    final = os.path.join(destino, f"{base}__{time.time_ns()}{ext}")
                os.rename(archivo, final)   # rename no pisa en Windows; en Linux `final` no existe
                movidos += 1
            except FileNotFoundError:
                continue   # otra instancia lo movió primero
            except OSError as exc:
                if logger:
                    logger.warning(f"No se pudo archivar {nombre}: {exc}")
    if movidos and logger:
        logger.info(f"PDF públicos archivados (no borrados): {movidos}")
    return movidos
