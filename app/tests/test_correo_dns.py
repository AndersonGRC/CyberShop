# -*- coding: utf-8 -*-
"""Verificación del dominio del correo: solo se rechaza lo que el DNS confirma
que no existe (NXDOMAIN). Caso real: gerencia@empresa.com se rechazaba porque
empresa.com no tiene sitio web (registro A) aunque el dominio sí existe."""
import socket

import pytest

from services import correo_service as c


def _sin_web(*_a, **_k):
    raise socket.gaierror(11001, 'sin registro A')


@pytest.mark.parametrize('rcode, esperado', [(0, True), (3, False)])
def test_responde_el_dns(monkeypatch, rcode, esperado):
    monkeypatch.setattr(c, '_consulta_dns', lambda dominio, **k: rcode)
    monkeypatch.setattr(c.socket, 'getaddrinfo', _sin_web)
    assert c._dominio_existe('empresa.com') is esperado


def test_dominio_corporativo_sin_web_se_acepta(monkeypatch):
    monkeypatch.setattr(c, '_consulta_dns', lambda dominio, **k: 0)    # existe (tiene MX/SOA)
    monkeypatch.setattr(c.socket, 'getaddrinfo', _sin_web)              # pero no tiene sitio web
    assert c.validar('gerencia@empresa.com') == ('gerencia@empresa.com', None)


def test_si_el_dns_no_responde_no_se_bloquea(monkeypatch):
    monkeypatch.setattr(c, '_consulta_dns', lambda dominio, **k: None)
    monkeypatch.setattr(c.socket, 'getaddrinfo', _sin_web)
    assert c._dominio_existe('empresa.com') is None
    assert c.validar('gerencia@empresa.com')[0] == 'gerencia@empresa.com'


def test_nxdomain_se_rechaza(monkeypatch):
    monkeypatch.setattr(c, '_consulta_dns', lambda dominio, **k: 3)
    correo, err = c.validar('ana@noexiste-zyx.com')
    assert correo is None and 'no existe' in err


def test_consulta_rechaza_etiquetas_invalidas():
    assert c._consulta_dns('a..b') is None
    assert c._consulta_dns('x' * 64 + '.com') is None
