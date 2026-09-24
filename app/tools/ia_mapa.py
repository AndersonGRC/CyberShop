"""Genera docs/IA_MAPA.md: qué sabe hacer el asistente y qué dispara cada cosa.

El mapa NO se escribe a mano: sale del registro único (services/ia/registro.py +
services/ia/intenciones.py). Así no puede quedar desactualizado sin que alguien
se entere — hay una prueba que regenera y compara.

Uso:
    python tools/ia_mapa.py            # escribe docs/IA_MAPA.md
    python tools/ia_mapa.py --stdout   # lo imprime, sin tocar el archivo
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DESTINO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'docs', 'IA_MAPA.md')

_CANAL = {'panel': 'Panel', 'publico': 'Público'}
_MOTOR = {'A': 'A · cualquiera', 'B': 'B · mejor con el bueno', 'C': 'C · exige el profundo'}


def _celda(valor):
    """Texto de celda de tabla: sin tuberías sueltas ni saltos."""
    return str(valor).replace('|', '/').replace('\n', ' ').strip()


def generar():
    # Importar el paquete de dominios es lo que POBLA el registro: sus módulos
    # llaman a registrar() al cargarse. Sin esto el mapa sale vacío.
    import services.ia_datos  # noqa: F401
    from services.ia.registro import mapa

    filas = mapa()
    out = []
    a = out.append
    a('# Mapa del Asistente IA')
    a('')
    a('> **Generado**: no editar a mano. Sale de `services/ia/registro.py` +')
    a('> `services/ia/intenciones.py`. Para regenerarlo: `python tools/ia_mapa.py`.')
    a('')
    a('Así decide el asistente qué hacer con una pregunta:')
    a('')
    a('1. **Palabras clave** (`services/ia/enrutador.py`): si la pregunta contiene una de las frases')
    a('   de la columna «Se dispara con», se ejecuta esa función **sin gastar modelo**.')
    a('2. **Índice de textos** (RAG, `services/ia_rag/`): para preguntas de prosa —envíos, garantía,')
    a('   quiénes somos— se busca en los documentos del negocio.')
    a('3. **El modelo elige**: si nada de lo anterior aplica, se le muestra el catálogo y responde')
    a('   con un JSON indicando qué función usar. **Nunca escribe SQL.**')
    a('')
    a('En todos los casos, los datos los pone la consulta: el modelo solo redacta con lo que recibe.')
    a('')
    a(f'**Capacidades registradas: {len(filas)}**')
    a('')

    por_dominio = {}
    for f in filas:
        por_dominio.setdefault(f['dominio'], []).append(f)

    for dominio in sorted(por_dominio):
        a(f'## {dominio.capitalize()}')
        a('')
        a('| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |')
        a('|---|---|---|---|---|---|---|')
        for f in por_dominio[dominio]:
            disp = ' · '.join(f'`{d}`' for d in f['disparadores']) or '_(solo la elige el modelo)_'
            params = ', '.join(f['params']) or '—'
            canal = ' + '.join(_CANAL.get(c, c) for c in f['canales'])
            permiso = f['permiso'] or 'cualquiera del panel'
            if f['sensible']:
                permiso += f" · **sensible: {f['sensible']}**"
            if f['modulos']:
                permiso += f" · módulo {'/'.join(f['modulos'])}"
            a(f"| `{f['code']}` | {_celda(f['descripcion'])} | {_celda(disp)} | {params} | "
              f"{canal} | {_MOTOR.get(f['motor'], f['motor'])} | {_celda(permiso)} |")
        a('')

    a('## Preguntas de ejemplo')
    a('')
    a('Las usa la prueba del enrutador: cada una debe caer en su función.')
    a('')
    for f in filas:
        for ej in f['ejemplos']:
            a(f"- «{ej}» → `{f['code']}`")
    a('')
    return '\n'.join(out)


if __name__ == '__main__':
    texto = generar()
    if '--stdout' in sys.argv:
        sys.stdout.reconfigure(encoding='utf-8')
        print(texto)
    else:
        os.makedirs(os.path.dirname(DESTINO), exist_ok=True)
        with open(DESTINO, 'w', encoding='utf-8', newline='\n') as f:
            f.write(texto)
        print(f'Escrito {DESTINO} ({len(texto)} caracteres)')
