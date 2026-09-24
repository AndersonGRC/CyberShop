"""Mide cuantos tokens cuesta cada tipo de mensaje que manda CyberShop.

Usa /v1/messages/count_tokens, que NO consume creditos: sirve para validar la
clave y para calcular el costo real antes de gastar un peso.
"""
import os, sys
import requests

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r'C:/Cybershop/CyberShop/app')
os.chdir(r'C:/Cybershop/CyberShop/app')
os.environ.setdefault('DB_NAME', 'cybershop_test')
os.environ.setdefault('FLASK_SECRET_KEY', 'prueba')

CLAVE = os.environ['ANTHROPIC_API_KEY']
MODELO = os.environ.get('MODELO', 'claude-haiku-4-5-20251001')
P_IN, P_OUT = 1.0, 5.0        # US$ por millon de tokens (entrada / salida)


def contar(sistema, usuario):
    r = requests.post('https://api.anthropic.com/v1/messages/count_tokens',
                      headers={'x-api-key': CLAVE, 'anthropic-version': '2023-06-01',
                               'content-type': 'application/json'},
                      json={'model': MODELO, 'system': sistema,
                            'messages': [{'role': 'user', 'content': usuario}]},
                      timeout=20)
    if r.status_code != 200:
        return None, f'{r.status_code}: {r.text[:120]}'
    return r.json().get('input_tokens'), None


from app import app                      # noqa: E402
import services.chat_publico.motor as pub  # noqa: E402
import services.ai_service as ai         # noqa: E402

casos = []
with app.test_request_context('/'):
    # 1) Chat del sitio: la redaccion sobre datos ya resueltos
    for pregunta in ('¿hacen domicilios?', '¿tienen gaseosa?'):
        plan = pub.preparar(pregunta)
        s, u = pub._prompt(plan)
        casos.append((f'chat sitio: {pregunta}', s, u, 120))

    # 2) Chat del panel: el prompt de redaccion con datos reales del negocio
    import services.ai_tools as tools
    from services.ia_datos.acceso import Contexto
    datos = tools.ejecutar('ventas_periodo', {'periodo': 'mes'}, Contexto(canal='sistema'))
    import json
    s = ai._contexto_tenant() + " Responde usando UNICAMENTE los datos dados."
    u = f"Pregunta: «¿cuanto vendi este mes?»\nDatos (JSON):\n{json.dumps(datos, ensure_ascii=False, default=str)}\n\nRedacta."
    casos.append(('chat panel: redaccion con datos', s, u, 350))

    # 3) El enrutador (lo mas caro del panel: lleva el catalogo completo)
    permitidas = tools.permitidas(Contexto(canal='web', rol_id=2))
    s = tools.CONTEXTO_DATOS + "\n\nEres un enrutador. Elige de esta lista:\n" + \
        tools.catalogo_para_prompt(permitidas) + "\nResponde SOLO JSON."
    casos.append(('chat panel: elegir herramienta (catalogo)', s, '¿cuanto vendi este mes?', 220))

print(f'Modelo: {MODELO}   ·   precios usados: US${P_IN}/M entrada, US${P_OUT}/M salida\n')
print(f"{'caso':44s} {'entrada':>8s} {'salida~':>8s} {'US$/mensaje':>12s}")
total = 0
for nombre, sistema, usuario, salida in casos:
    n, err = contar(sistema, usuario)
    if err:
        print(f'{nombre:44s} ERROR {err}')
        continue
    costo = n / 1e6 * P_IN + salida / 1e6 * P_OUT
    total += costo
    print(f'{nombre:44s} {n:8d} {salida:8d} {costo:12.6f}')
print(f'\nUna conversacion tipica del sitio (3 mensajes): US$ {total/len(casos)*3:.5f}')
print(f'1.000 mensajes del sitio: US$ {total/len(casos)*1000:.2f}')
