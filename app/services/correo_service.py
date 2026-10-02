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
import random
import re
import socket
import struct
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
# Resolvers públicos para la consulta MX (la librería estándar no consulta MX).
_RESOLVERS = (('1.1.1.1', 53), ('8.8.8.8', 53))


def _consulta_dns(dominio, tipo=15, servidor=('1.1.1.1', 53), espera=2.0):
    """Consulta DNS mínima por UDP (tipo 15 = MX). Devuelve el código de
    respuesta (0 = existe, 3 = NXDOMAIN, el dominio no existe) o None."""
    try:
        etiquetas = [e.encode('idna') for e in dominio.strip('.').split('.')]
        if not etiquetas or any(not e or len(e) > 63 for e in etiquetas):
            return None
        tid = random.randint(0, 0xFFFF)
        pregunta = b''.join(bytes([len(e)]) + e for e in etiquetas) + b'\x00' + struct.pack('>HH', tipo, 1)
        paquete = struct.pack('>HHHHHH', tid, 0x0100, 1, 0, 0, 0) + pregunta
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(espera)
            sock.sendto(paquete, servidor)
            datos, _ = sock.recvfrom(1024)
        if len(datos) < 12:
            return None
        rtid, banderas = struct.unpack('>HH', datos[:4])
        if rtid != tid or not banderas & 0x8000:
            return None
        return banderas & 0x000F
    except Exception:  # noqa: BLE001
        return None


def _dominio_existe(dominio, segundos=3.0):
    """True si el dominio existe, False SOLO si el DNS responde que no existe
    (NXDOMAIN), None si no se pudo saber.

    Antes se usaba getaddrinfo, que busca el SITIO web (registro A): un dominio
    corporativo con correo pero sin web en el dominio pelado (p. ej. empresa.com)
    se rechazaba como inexistente. Un correo vive en el registro MX; aquí solo
    se rechaza lo que el DNS confirma que no existe."""
    def consultar():
        for servidor in _RESOLVERS:
            rcode = _consulta_dns(dominio, servidor=servidor)
            if rcode == 0:
                return True
            if rcode == 3:
                return False
        try:                      # sin respuesta de los resolvers: solo prueba positiva
            socket.getaddrinfo(dominio, None)
            return True
        except Exception:  # noqa: BLE001
            return None
    try:
        return _dns.submit(consultar).result(timeout=segundos + 2)
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
