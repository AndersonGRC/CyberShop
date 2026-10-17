"""Evalúa la IA en las notas adicionales de cotizaciones con el banco de 100 casos
(tools/ia_datasets/notas_cotizacion/banco_notas_cotizacion.json).

Por cada caso llama a ia_notas_cotizacion.sugerir (el mismo camino de la app) y dice:
de dónde salió la respuesta (ia / base), cuántas secciones y notas trajo, cuántas notas se
descartaron (normas inventadas, cláusulas abusivas o repetidas) y si avisó en los casos
donde el negocio pidió algo abusivo. Sirve para comparar el modelo antes y después de
afinarlo. Necesita la IA encendida y el módulo Asistente IA activo en la tienda.

Uso:
    python tools/ia_notas_banco.py              # los 100 casos
    python tools/ia_notas_banco.py 10           # solo los primeros 10
    python tools/ia_notas_banco.py 10 --todo    # y muestra las notas de cada caso
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402

BANCO = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ia_datasets', 'notas_cotizacion',
                     'banco_notas_cotizacion.json')


def main():
    from services import ia_notas_cotizacion as inc

    casos = json.load(open(BANCO, encoding='utf-8'))
    numeros = [a for a in sys.argv[1:] if a.isdigit()]
    if numeros:
        casos = casos[:int(numeros[0])]
    resumen = {'ia': 0, 'base': 0, 'vacio': 0}
    descartadas = sin_aviso = sin_redactar = 0
    inicio = time.time()
    with app.test_request_context('/admin/cotizar'):
        for i, caso in enumerate(casos):
            t = time.time()
            r = inc.sugerir(caso['items'], caso['cliente'], caso['indicaciones'], caso['notas_actuales'])
            notas = sum(len(s['notas']) for s in r['secciones'])
            resumen[r['origen']] = resumen.get(r['origen'], 0) + 1
            descartadas += r.get('descartadas', 0)
            falta_aviso = caso['pide_algo_abusivo'] and not r['avisos']
            sin_aviso += falta_aviso
            # ¿La condición propia del negocio la redactó la IA (o tuvo que entrar la del catálogo)?
            todas = [n for s in r['secciones'] for n in s['notas']]
            de_catalogo = [c for c in caso.get('condiciones_esperadas', []) if c in todas]
            sin_redactar += bool(de_catalogo) and r['origen'] == 'ia'
            print(f"{i:3d} {r['origen']:5s} {len(r['secciones'])} secc. {notas:2d} notas "
                  f"desc.={r.get('descartadas', 0)} {time.time() - t:5.1f}s  {caso['negocio']}"
                  + ('  ¡SIN AVISO!' if falta_aviso else '')
                  + ('  (condición sin redactar por la IA)' if de_catalogo and r['origen'] == 'ia' else ''))
            if '--todo' in sys.argv:
                for s in r['secciones']:
                    print('      ##', s['titulo'])
                    for n in s['notas']:
                        print('       -', n)
                for a in r['avisos']:
                    print('      AVISO:', a)
    total = len(casos) or 1
    print(f"\nRespondió la IA: {resumen['ia']}/{len(casos)} ({resumen['ia'] / total * 100:.0f} %); "
          f"sugerencias base: {resumen['base']}")
    print(f'Notas descartadas por el filtro: {descartadas}; casos abusivos sin aviso: {sin_aviso}; '
          f'condiciones del negocio que la IA no redactó: {sin_redactar}')
    print(f'Tiempo total: {time.time() - inicio:.0f} s')


if __name__ == '__main__':
    main()
