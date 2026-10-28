# -*- coding: utf-8 -*-
"""El evento Purchase hacia Meta solo puede salir de RealSaleNotifier.

Antes salía dos veces desde la página de respuesta de PayU (píxel del navegador
+ API de conversiones): se repetía al recargar, tomaba el valor de la URL y no
salía si el cliente cerraba el navegador. Esta prueba revisa el código (sin
base de datos) y falla si vuelve a aparecer en otro archivo."""
import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
NOTIFICADOR = 'services/real_sale_notifier.py'
TRANSPORTE = 'services/meta_capi.py'            # el único que habla con la Graph API
EXTENSIONES = {'.py', '.js', '.mjs', '.html', '.htm', '.jinja', '.j2', '.sql', '.json'}
IGNORADAS = {'venv', 'env', '.venv', 'node_modules', 'site-packages', '__pycache__',
             '.pytest_cache', '.git', 'tests'}

REGLAS = [
    # fbq('track', 'Purchase'…), fbq('trackSingle', '<píxel>', 'Purchase'…), trackCustom…
    ('fbq() con Purchase', re.compile(r"fbq\s*\([^)]{0,200}?['\"]Purchase['\"]", re.S), set()),
    # Píxel de imagen: facebook.com/tr?…&ev=Purchase
    ('facebook.com/tr con ev=Purchase', re.compile(r"facebook\.com/tr[^'\"\s]*ev=Purchase", re.I), set()),
    # event_name='Purchase', {"event_name": "Purchase"}, send_event_async('Purchase', …)
    ("'Purchase' fuera del notificador", re.compile(r"['\"]Purchase['\"]"), {NOTIFICADOR}),
    # Una llamada directa a la Graph API se saltaría el notificador
    ('graph.facebook.com fuera del transporte', re.compile(r"graph\.facebook\.com", re.I),
     {NOTIFICADOR, TRANSPORTE}),
]


def _archivos():
    for archivo in APP.rglob('*'):
        rel = archivo.relative_to(APP)
        if (archivo.is_file() and archivo.suffix.lower() in EXTENSIONES
                and not IGNORADAS.intersection(rel.parts[:-1])):
            yield rel.as_posix(), archivo


def test_purchase_solo_sale_de_real_sale_notifier():
    hallazgos = []
    for rel, archivo in _archivos():
        texto = archivo.read_text(encoding='utf-8', errors='replace')
        for nombre, patron, permitidos in REGLAS:
            if rel in permitidos:
                continue
            for m in patron.finditer(texto):
                hallazgos.append(f'{rel}:{texto.count(chr(10), 0, m.start()) + 1} [{nombre}]')
    assert not hallazgos, 'Purchase hacia Meta fuera de RealSaleNotifier:\n' + '\n'.join(hallazgos)


def test_la_guarda_detecta_las_formas_conocidas():
    """La guarda no puede quedar ciega: cada forma de enviar Purchase la dispara."""
    casos = [
        "fbq('track', 'Purchase', {value: 1})",
        'fbq("trackSingle", "4412332785657284", "Purchase", {})',
        '<img src="https://www.facebook.com/tr?id=1&ev=Purchase&noscript=1">',
        "send_event_async(event_name='Purchase', event_id='x', user_data={})",
        "requests.post('https://graph.facebook.com/v18.0/1/events', json=p)",
    ]
    for caso in casos:
        assert any(patron.search(caso) for _, patron, _ in REGLAS), caso
    assert (APP / NOTIFICADOR).is_file() and (APP / TRANSPORTE).is_file()
