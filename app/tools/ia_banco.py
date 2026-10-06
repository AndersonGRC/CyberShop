"""Mide cuánto entiende el asistente del panel SIN modelo.

Recorre el banco de preguntas (tests/banco_preguntas_panel.py) por la ruta
rápida del panel y dice cuáles llegan a la consulta correcta, cuáles a otra
y cuáles se quedan sin ruta (las resolvería el modelo).

Uso:
    python tools/ia_banco.py            # resumen + fallas
    python tools/ia_banco.py --todo     # también las que pasan
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    import services.ia_datos as d
    from services.ia.enrutador import enrutar_panel_seguro
    from tests.banco_preguntas_panel import AL_MODELO, BANCO

    # Lo que ve el panel: solo capacidades declaradas para el panel.
    caps = [h for h in d.REGISTRO.values() if 'panel' in h.canales]
    bien, mal, sin = [], [], []
    for pregunta, esperada in BANCO:
        r = enrutar_panel_seguro(pregunta, caps)
        if r and r[0][0] == esperada:
            bien.append((pregunta, r[0]))
        elif r:
            mal.append((pregunta, esperada, r[0][0]))
        else:
            sin.append((pregunta, esperada))
    falsos = [(q, enrutar_panel_seguro(q, caps)) for q in AL_MODELO if enrutar_panel_seguro(q, caps)]

    print(f'Entiende sin modelo: {len(bien)}/{len(BANCO)} ({len(bien) / len(BANCO) * 100:.0f}%)')
    for q, esperada, got in mal:
        print(f'  OTRA   «{q}» → {got} (esperaba {esperada})')
    for q, esperada in sin:
        print(f'  NADA   «{q}» (esperaba {esperada})')
    for q, r in falsos:
        print(f'  DEBIA IR AL MODELO «{q}» → {r}')
    if '--todo' in sys.argv:
        for q, r in bien:
            print(f'  ok     «{q}» → {r}')

    # Chat del sitio público (visitante anónimo).
    from services.ia.enrutador import enrutar
    from tests.banco_preguntas_panel import PUBLICO, SEGUIMIENTOS
    publicas = [h for h in d.REGISTRO.values() if 'publico' in h.canales]
    mal_pub = [(q, e, enrutar(q, publicas)) for q, e in PUBLICO
               if not (enrutar(q, publicas) and enrutar(q, publicas)[0][0] == e)]
    print(f'Chat del sitio: {len(PUBLICO) - len(mal_pub)}/{len(PUBLICO)}')
    for q, e, r in mal_pub:
        print(f'  FALLA  «{q}» → {r} (esperaba {e})')

    # Seguimientos «¿y el mes pasado?» tras una consulta.
    mal_seg = []
    for anterior, q, periodo in SEGUIMIENTOS:
        r = enrutar_panel_seguro(q, caps, historial=[{'pregunta': 'x', 'herramienta': anterior}])
        esperado = [(anterior, {'periodo': periodo})] if periodo else []
        if r != esperado:
            mal_seg.append((anterior, q, r, esperado))
    print(f'Seguimientos: {len(SEGUIMIENTOS) - len(mal_seg)}/{len(SEGUIMIENTOS)}')
    for anterior, q, r, esperado in mal_seg:
        print(f'  FALLA  tras {anterior}: «{q}» → {r} (esperaba {esperado})')
    return 0 if not (mal or falsos or mal_pub or mal_seg) else 1


if __name__ == '__main__':
    sys.exit(main())
