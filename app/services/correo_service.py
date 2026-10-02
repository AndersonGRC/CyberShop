"""Validación de correos del registro público (prueba gratis).

El filtro definitivo es el enlace de confirmación: sin abrirlo no se crea
nada. Esto solo ataja temprano lo evidente para que la persona lo corrija
antes de esperar un correo que nunca llegará:

- forma del correo;
- dominios de correo desechable (mailinator, yopmail, 10minutemail…);
- errores de digitación comunes (gmial.com → gmail.com) con sugerencia;
- que el dominio exista (DNS con tiempo límite; si el DNS del servidor falla
  no se bloquea: decide la confirmación).
"""
import re
import socket
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _Timeout

_FORMA = re.compile(r'^[a-z0-9._%+\-]{1,64}@([a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?)+)$')

DESECHABLES = {
    'mailinator.com', 'yopmail.com', 'yopmail.net', '10minutemail.com', '10minutemail.net',
    'guerrillamail.com', 'guerrillamail.net', 'sharklasers.com', 'tempmail.com', 'temp-mail.org',
    'tempmail.net', 'trashmail.com', 'getnada.com', 'nada.email', 'maildrop.cc', 'dispostable.com',
    'fakeinbox.com', 'mintemail.com', 'throwawaymail.com', 'mohmal.com', 'emailondeck.com',
    'mailnesia.com', 'spamgourmet.com', 'tempinbox.com', 'mytemp.email', 'tmpmail.org',
    'burnermail.io', 'minuteinbox.com', 'mail.tm', 'example.com', 'test.com',
}

# Digitación frecuente → dominio correcto (se sugiere, no se corrige solo).
TYPOS = {
    'gmial.com': 'gmail.com', 'gmal.com': 'gmail.com', 'gamil.com': 'gmail.com', 'gmai.com': 'gmail.com',
    'gmail.co': 'gmail.com', 'gmail.con': 'gmail.com', 'gmail.cm': 'gmail.com', 'gmaill.com': 'gmail.com',
    'gnail.com': 'gmail.com', 'gimail.com': 'gmail.com', 'gmail.es': 'gmail.com', 'gmail.om': 'gmail.com',
    'hotmial.com': 'hotmail.com', 'hotmal.com': 'hotmail.com', 'hotmail.co': 'hotmail.com',
    'hotmail.con': 'hotmail.com', 'homail.com': 'hotmail.com', 'hotmai.com': 'hotmail.com',
    'outlok.com': 'outlook.com', 'outloo.com': 'outlook.com', 'outlook.co': 'outlook.com',
    'outlook.con': 'outlook.com', 'yaho.com': 'yahoo.com', 'yahoo.co': 'yahoo.com',
    'yahoo.con': 'yahoo.com', 'yhaoo.com': 'yahoo.com', 'icloud.co': 'icloud.com', 'iclod.com': 'icloud.com',
}

_dns = ThreadPoolExecutor(max_workers=4, thread_name_prefix='dns-correo')


def _dominio_existe(dominio, segundos=3.0):
    """True/False si el DNS respondió; None si no se pudo saber a tiempo."""
    def consultar():
        try:
            socket.getaddrinfo(dominio, None)
            return True
        except socket.gaierror as exc:
            # EAI_NONAME / EAI_NODATA: el dominio no existe. Otros: no se sabe.
            return False if exc.errno in (socket.EAI_NONAME, getattr(socket, 'EAI_NODATA', -5), 11001) else None
        except Exception:  # noqa: BLE001
            return None
    try:
        return _dns.submit(consultar).result(timeout=segundos)
    except _Timeout:
        return None


def validar(email, comprobar_dominio=True):
    """(correo_normalizado, None) o (None, mensaje para la persona)."""
    correo = str(email or '').strip().lower()
    m = _FORMA.match(correo)
    if not m or '..' in correo:
        return None, 'Escribe un correo válido, por ejemplo tunombre@gmail.com.'
    dominio = m.group(1)
    if dominio in TYPOS:
        sugerido = correo.split('@')[0] + '@' + TYPOS[dominio]
        return None, f'¿Quisiste decir {sugerido}? Revisa cómo escribiste tu correo.'
    if dominio in DESECHABLES:
        return None, ('Ese tipo de correo es temporal y no recibe nuestros mensajes por mucho tiempo. '
                      'Usa tu correo personal o el de tu negocio.')
    if comprobar_dominio and _dominio_existe(dominio) is False:
        return None, f'El dominio «{dominio}» no existe. Revisa cómo escribiste tu correo.'
    return correo, None
