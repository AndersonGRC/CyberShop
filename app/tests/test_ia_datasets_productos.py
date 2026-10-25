# -*- coding: utf-8 -*-
"""Bancos de fine-tuning para ingresar productos con la IA:
- ingreso_productos: la orden del chat → el plan JSON que acepta el servidor;
- productos_similares: antes de crear, ¿es duplicado, otra presentación, otra marca o hay
  que preguntar?"""
import json


def test_banco_ingreso_productos_lo_acepta_el_servidor():
    from tools import ia_productos_dataset as ds
    filas, rechazados = ds.construir()
    assert len(filas) >= 80, 'ejemplos que el servidor aceptaría tal cual'
    for fila in filas:
        system, user, assistant = (m['content'] for m in fila['messages'])
        plan = json.loads(assistant)
        assert user.startswith('<datos_orden_json>') and 'PROCESO ' in system
        assert plan['tipo'] in ('aclarar', fila['proceso'])
    # Los rechazados son frases normales que el filtro del servidor aún no entiende:
    # quedan a la vista para corregir el filtro (no se arreglan con fine-tuning).
    assert all(motivo for _, motivo in rechazados)


def test_banco_productos_similares():
    from tools import ia_similares_dataset as ds
    lista = ds.casos()
    assert len(lista) == 100
    decisiones = {r['decision'] for *_, r in lista}
    assert decisiones == {'duplicado', 'variante', 'distinto', 'aclarar'}
    for negocio, nuevo, cat, r in lista:
        ids = {p['id'] for p in cat}
        if r['decision'] == 'duplicado':
            assert r['producto_id'] in ids and r['nombre_sugerido'] is None
        elif r['decision'] == 'variante':
            assert r['producto_id'] is None and r['nombre_sugerido']
            assert r['nombre_sugerido'] not in {p['nombre'] for p in cat}, 'la variante no repite un nombre'
        elif r['decision'] == 'aclarar':
            assert r['pregunta'] and all(p['nombre'] in r['pregunta'] for p in cat)
        else:
            assert r['producto_id'] is None
        assert json.loads(json.dumps(r)) == r
