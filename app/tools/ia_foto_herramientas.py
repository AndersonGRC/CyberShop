"""Foto COMPLETA del asistente: salida de las 37 herramientas + sus metadatos +
el catálogo que ve el modelo, contra cybershop_test.

Se corre ANTES y DESPUÉS de reorganizar el registro (F0.1). Los dos JSON deben
ser idénticos: si algo cambia, se rompió algo que el dueño ya usaba.

Uso: python foto_ia_completa.py <salida.json>
"""
import json
import os
import sys

os.environ['DB_NAME'] = 'cybershop_test'
os.environ.setdefault('FLASK_SECRET_KEY', 'prueba')
sys.path.insert(0, r'C:/Cybershop/CyberShop/app')
os.chdir(r'C:/Cybershop/CyberShop/app')

from app import app  # noqa: E402
from database import get_db_cursor  # noqa: E402
import services.ai_tools as tools  # noqa: E402
from services.ia_datos.acceso import Contexto  # noqa: E402

PERIODOS = ('hoy', 'ayer', 'semana', 'semana_anterior', 'mes', 'mes_anterior', 'anio', 'todo')


def _nombre(sql, defecto):
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(sql)
            r = cur.fetchone()
            return (list(r.values())[0] if r else None) or defecto
    except Exception:
        return defecto


# Contexto de request con sesión de dueño: hay herramientas (alertas_negocio) que
# leen la sesión y fuera de un request revientan.
with app.test_request_context('/admin/ia/'):
    from flask import session
    session['usuario_id'] = 1
    session['rol_id'] = 2
    # Valores reales para los parámetros de nombre (deterministas: el primero alfabético).
    nombres = {
        'cliente': _nombre("SELECT cliente_nombre FROM pedidos WHERE cliente_nombre IS NOT NULL "
                           "ORDER BY cliente_nombre LIMIT 1", 'Ana'),
        'producto': _nombre("SELECT nombre FROM productos ORDER BY nombre LIMIT 1", 'producto'),
        'empleado': _nombre("SELECT nombre FROM empleados ORDER BY nombre LIMIT 1", 'empleado'),
    }

    # Contextos: 'sistema' para lo normal; dueño (rol 2) para lo sensible (nómina),
    # que es justo el camino real de permisos.
    ctx_sistema = Contexto(canal='sistema')
    ctx_dueno = Contexto(canal='web', rol_id=2, usuario_id=1)

    foto = {'_nombres_usados': nombres, '_catalogo': {}, '_resultados': {}}

    for code, h in sorted(tools.REGISTRO.items()):
        foto['_catalogo'][code] = {
            'descripcion': h.descripcion,
            'params': list(h.params),
            'etiqueta': h.etiqueta,
            'dominio': h.dominio,
            'modulos': list(h.modulos),
            'permiso': h.permiso,
            'sensible': h.sensible,
        }

        # Un juego de parámetros por herramienta (todos los períodos si los acepta).
        juegos = []
        base = {}
        for p in h.params:
            if p in nombres:
                base[p] = nombres[p]
            elif p == 'limite':
                base[p] = 5
            elif p == 'umbral':
                base[p] = 5
        if 'periodo' in h.params:
            juegos = [dict(base, periodo=p) for p in PERIODOS]
            juegos.append(dict(base, desde='2026-08-01', hasta='2026-08-31'))
        else:
            juegos = [base]
        if code == 'productos_bajo_stock':
            juegos.append({})          # sin umbral: usa su default

        ctx = ctx_dueno if h.sensible else ctx_sistema
        for params in juegos:
            clave = f'{code}|{json.dumps(params, sort_keys=True, ensure_ascii=False)}'
            try:
                foto['_resultados'][clave] = tools.ejecutar(code, params, ctx)
            except Exception as exc:  # noqa: BLE001
                foto['_resultados'][clave] = {'_EXCEPCION': f'{type(exc).__name__}: {exc}'}

    # Lo que realmente ve el modelo, por rol: si esto cambia, cambia su comportamiento.
    for rol, nombre in ((1, 'admin'), (2, 'dueno'), (4, 'empleado'), (5, 'contador'),
                        (6, 'mesero'), (7, 'cajero')):
        c = Contexto(canal='web', rol_id=rol, usuario_id=1)
        permitidas = tools.permitidas(c)
        foto[f'_catalogo_prompt_{nombre}'] = tools.catalogo_para_prompt(permitidas)
    foto['_catalogo_prompt_escritorio'] = tools.catalogo_para_prompt(
        tools.permitidas(Contexto(canal='escritorio')))
    foto['_contexto_datos'] = tools.CONTEXTO_DATOS

with open(sys.argv[1], 'w', encoding='utf-8') as f:
    json.dump(foto, f, ensure_ascii=False, indent=1, sort_keys=True, default=str)
print(f"{len(foto['_resultados'])} resultados de {len(foto['_catalogo'])} herramientas en {sys.argv[1]}")
