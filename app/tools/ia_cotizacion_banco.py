"""Evalúa el análisis profundo de la cotización con IA con el banco de 100 casos
(tools/ia_datasets/cotizacion_auto/banco_cotizacion_auto.json).

Por cada caso le pide al modelo real (equipo de IA, motor de análisis profundo) la
propuesta, y compara con lo esperado: JSON válido, ítems y cantidades, precios de
referencia de cotizaciones anteriores, dudas y condiciones. Sirve para comparar el modelo
antes y después de afinarlo. Necesita el equipo de IA encendido (no usa la nube).

Uso:
    python tools/ia_cotizacion_banco.py          # los 100 casos
    python tools/ia_cotizacion_banco.py 10       # los primeros 10
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402

BANCO = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ia_datasets', 'cotizacion_auto',
                     'banco_cotizacion_auto.json')


def main():
    from services import ia_cotizacion_auto as auto

    casos = json.load(open(BANCO, encoding='utf-8'))
    numeros = [a for a in sys.argv[1:] if a.isdigit()]
    if numeros:
        casos = casos[:int(numeros[0])]
    cuenta = {'json': 0, 'items': 0, 'cantidades': 0, 'precios': 0, 'con_precio': 0, 'dudas': 0}
    inicio = time.time()
    with app.test_request_context('/admin/cotizar/ia/generar'):
        for i, caso in enumerate(casos):
            t = time.time()
            texto, err = auto._razonar(auto.SISTEMA_PLAN.format(negocio=caso['negocio']),
                                       auto.peticion_plan(caso['lectura'], caso['relacionados']))
            plan = auto.validar_plan(auto.extraer_json(texto)) if texto else None
            esperado = caso['esperado']
            if not plan:
                print(f'{i:3d} SIN JSON ({err or "respuesta inválida"})  {caso["negocio"]}')
                continue
            cuenta['json'] += 1
            obtenidos = [(x['descripcion'], x['cantidad']) for x in plan['items']]
            acierta = [any(auto.parecido(d, od) >= 0.6 for od, _ in obtenidos) for d, _ in esperado['items']]
            cantidades = [any(auto.parecido(d, od) >= 0.6 and c == oc for od, oc in obtenidos)
                          for d, c in esperado['items']]
            cuenta['items'] += all(acierta) and len(obtenidos) == len(esperado['items'])
            cuenta['cantidades'] += all(cantidades)
            referencias = [p for p in esperado['precio_referencia'] if p]
            if referencias:
                cuenta['con_precio'] += 1
                cuenta['precios'] += any(x['precio_referencia'] == referencias[0] for x in plan['items'])
            cuenta['dudas'] += bool(plan['dudas'])
            print(f'{i:3d} ítems {"ok" if all(acierta) else "MAL"} cant. {"ok" if all(cantidades) else "MAL"} '
                  f'({len(obtenidos)} vs {len(esperado["items"])}) dudas={len(plan["dudas"])} '
                  f'{time.time() - t:5.1f}s  {caso["negocio"]}')
    n = len(casos) or 1
    print(f"\nJSON válido: {cuenta['json']}/{len(casos)}; ítems exactos: {cuenta['items']}/{len(casos)}; "
          f"cantidades: {cuenta['cantidades']}/{len(casos)}; precio de la cotización anterior: "
          f"{cuenta['precios']}/{cuenta['con_precio']}; con dudas: {cuenta['dudas']}/{len(casos)}")
    print(f'Tiempo total: {time.time() - inicio:.0f} s ({(time.time() - inicio) / n:.0f} s por caso)')


if __name__ == '__main__':
    main()
