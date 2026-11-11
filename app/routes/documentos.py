# -*- coding: utf-8 -*-
"""routes/documentos.py — Enlace privado de una cotización o cuenta de cobro (1.9.19.0).

Lo abre el cliente de la tienda sin iniciar sesión, con el enlace que la tienda le
manda (WhatsApp o copiado). El enlace no se puede adivinar, solo sirve en la tienda
que lo creó y vence a los 30 días. Va en un blueprint aparte porque los de
cotizaciones y cuentas de cobro exigen sesión en todas sus rutas.
"""
from flask import Blueprint, Response, request

from services import documentos_privados as docs

documentos_bp = Blueprint('documentos', __name__)

_AVISOS = {
    'vencido':  ('Este enlace ya venció',
                 'Los enlaces duran 30 días. Pídele a la tienda que te lo envíe de nuevo.', 410),
    'invalido': ('Este enlace no es válido',
                 'Revisa que esté completo o pídele a la tienda que te lo envíe de nuevo.', 404),
    'no_esta':  ('Este documento ya no está disponible',
                 'Pídele a la tienda que te envíe uno nuevo.', 404),
    'espera':   ('Demasiadas visitas seguidas',
                 'Espera un minuto y vuelve a abrir el enlace.', 429),
}


def _aviso(clave):
    titulo, texto, codigo = _AVISOS[clave]
    html = (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex, nofollow">'
        f'<title>{titulo}</title></head>'
        '<body style="margin:0;font-family:system-ui,Segoe UI,Arial,sans-serif;background:#f4f5f7;color:#1f2933">'
        '<div style="max-width:420px;margin:18vh auto 0;padding:28px 24px;background:#fff;'
        'border-radius:14px;box-shadow:0 6px 24px rgba(0,0,0,.08);text-align:center">'
        f'<h1 style="font-size:1.25rem;margin:0 0 10px">{titulo}</h1>'
        f'<p style="margin:0;line-height:1.5;color:#52606d">{texto}</p>'
        '</div></body></html>'
    )
    respuesta = Response(html, status=codigo, mimetype='text/html')
    respuesta.headers['Cache-Control'] = 'no-store'
    respuesta.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return respuesta


@documentos_bp.route('/doc/<token>')
def ver(token):
    """El PDF de la cotización o la cuenta de cobro de ese enlace."""
    from security import controlar_tasa_solicitudes
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or '?').split(',')[0].strip()
    if not controlar_tasa_solicitudes(f"doc:{ip}", max_requests=30, interval=60):
        return _aviso('espera')
    tipo, doc_id, estado = docs.leer_token(token)
    if estado != 'ok':
        return _aviso(estado)
    contenido = docs.pdf_de(tipo, doc_id)
    if not contenido:
        return _aviso('no_esta')
    return docs.respuesta_pdf(contenido, docs.nombre_archivo(tipo, doc_id))
