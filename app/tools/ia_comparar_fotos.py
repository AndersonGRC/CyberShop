"""Compara dos fotos del asistente ignorando lo que depende del reloj.

Uso: python comparar_fotos.py antes.json despues.json
Sale 0 si son equivalentes, 1 si hay una diferencia real.
"""
import json
import re
import sys

# Campos que cambian solos con el paso del tiempo entre una foto y otra.
RELOJ = re.compile(r'(hace_minutos|hace_dias|hace_horas|minutos_abierta|_ms$|duracion)', re.I)


def podar(obj):
    if isinstance(obj, dict):
        return {k: ('<reloj>' if RELOJ.search(k) else podar(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [podar(x) for x in obj]
    return obj


a = podar(json.load(open(sys.argv[1], encoding='utf-8')))
b = podar(json.load(open(sys.argv[2], encoding='utf-8')))

if a == b:
    print('IDENTICAS (ignorando campos que dependen del reloj)')
    sys.exit(0)

difs = [k for k in set(a) | set(b) if a.get(k) != b.get(k)]
print('DIFERENCIAS en:', difs)
for k in difs:
    va, vb = a.get(k), b.get(k)
    if isinstance(va, dict) and isinstance(vb, dict):
        for sub in sorted(set(va) | set(vb)):
            if va.get(sub) != vb.get(sub):
                print(f'  [{k}] {sub}')
                print(f'    antes:   {json.dumps(va.get(sub), ensure_ascii=False)[:300]}')
                print(f'    despues: {json.dumps(vb.get(sub), ensure_ascii=False)[:300]}')
sys.exit(1)
