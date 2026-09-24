"""Mide los modelos que ya están descargados en esta máquina (F1 del plan).

Responde tres cosas por modelo:
  - ¿corre en GPU o en CPU? (lo dice /api/ps: size_vram vs size)
  - ¿cuánto tarda en cargar en frío?
  - ¿a qué velocidad escribe? (palabras/s aproximadas)

Descarga el modelo de memoria al terminar (keep_alive=0): no deja nada cargado.
"""
import json
import sys
import time

import requests

BASE = 'http://127.0.0.1:11434'
PROMPT = ('Eres el asistente de una tienda. Responde en dos frases: un cliente pregunta '
          'si hacen domicilios y cuánto cuesta el envío. El envío urbano cuesta $8.000 '
          'y es gratis por compras sobre $150.000.')
MODELOS = sys.argv[1:] or ['qwen2.5:7b', 'gpt-oss-cyber', 'deepseek-r1:14b', 'qwen2.5-coder:14b']


def descargar(modelo):
    try:
        requests.post(f'{BASE}/api/generate', json={'model': modelo, 'keep_alive': 0}, timeout=60)
    except Exception:
        pass


def ps():
    try:
        return (requests.get(f'{BASE}/api/ps', timeout=5).json() or {}).get('models', [])
    except Exception:
        return []


def medir(modelo):
    descargar(modelo)                      # asegurar arranque EN FRÍO
    time.sleep(2)
    t0 = time.time()
    try:
        r = requests.post(f'{BASE}/api/generate', json={
            'model': modelo, 'prompt': PROMPT, 'stream': False,
            'options': {'num_predict': 80, 'temperature': 0.3},
        }, timeout=(10, 900))
        r.raise_for_status()
        d = r.json()
    except Exception as exc:
        return {'modelo': modelo, 'error': str(exc)[:160]}
    total = time.time() - t0

    cargados = {m.get('name'): m for m in ps()}
    info = cargados.get(modelo) or cargados.get(f'{modelo}:latest') or {}
    tam, vram = info.get('size') or 0, info.get('size_vram') or 0
    if not tam:
        donde = 'no se pudo saber'
    elif vram >= tam * 0.98:
        donde = 'GPU (todo)'
    elif vram <= tam * 0.02:
        donde = 'CPU (todo)'
    else:
        donde = f'mixto: {vram / tam * 100:.0f}% en GPU'

    ns = 1_000_000_000
    eval_dur = (d.get('eval_duration') or 0) / ns
    salida = {
        'modelo': modelo,
        'donde_corre': donde,
        'vram_gb': round(vram / 1024 ** 3, 2),
        'tamano_gb': round(tam / 1024 ** 3, 2),
        'carga_s': round((d.get('load_duration') or 0) / ns, 1),
        'primera_respuesta_s': round(total, 1),
        'tokens_generados': d.get('eval_count'),
        'tokens_por_s': round((d.get('eval_count') or 0) / eval_dur, 1) if eval_dur else None,
        'prompt_tokens_por_s': round((d.get('prompt_eval_count') or 0) /
                                     ((d.get('prompt_eval_duration') or 1) / ns), 1),
        'respuesta': (d.get('response') or '').strip().replace('\n', ' ')[:110],
    }
    descargar(modelo)
    return salida


resultados = []
for m in MODELOS:
    print(f'midiendo {m} ...', flush=True)
    resultados.append(medir(m))

print()
print(json.dumps(resultados, ensure_ascii=False, indent=1))
print()
print(f"{'modelo':22s} {'donde':16s} {'carga':>7s} {'1a resp':>8s} {'tok/s':>7s}")
for r in resultados:
    if 'error' in r:
        print(f"{r['modelo']:22s} ERROR: {r['error'][:60]}")
    else:
        print(f"{r['modelo']:22s} {r['donde_corre']:16s} {r['carga_s']:6.1f}s "
              f"{r['primera_respuesta_s']:7.1f}s {r['tokens_por_s']:6.1f}")
