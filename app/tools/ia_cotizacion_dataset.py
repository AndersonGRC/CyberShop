"""Banco de 100 ejemplos para afinar (fine-tuning) la IA que arma cotizaciones a partir de
lo que mandó el cliente (1.9.14.0).

Cada ejemplo es una conversación (sistema, petición, respuesta ideal) con EXACTAMENTE el
formato que usa la app (services/ia_cotizacion_auto.py, paso «razonar»): la petición trae
la conversación de WhatsApp (como la transcribe la IA de visión o como sale del chat
exportado), a veces una cotización anterior en PDF y los productos del catálogo; la
respuesta ideal es el JSON con cliente, ítems (con su porqué), condiciones y dudas.

Lo que enseña:
  - cotizar solo lo pedido (lo agregado va «sugerido», con su razón);
  - las cantidades que dijo el cliente; lo que falte, como duda para preguntarle;
  - usar el nombre exacto del catálogo y los precios de cotizaciones anteriores;
  - nunca inventar precios (null si no hay referencia);
  - sacar las condiciones habladas (anticipo, fecha, factura, transporte).

50 negocios × 2 variantes; nombres, teléfonos y empresas inventados.

Uso:
    python tools/ia_cotizacion_dataset.py     # escribe tools/ia_datasets/cotizacion_auto/
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import ia_cotizacion_auto as auto  # noqa: E402
from services import notas_cotizacion as nc  # noqa: E402
from tools.ia_notas_dataset import NEGOCIOS  # noqa: E402

SALIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ia_datasets', 'cotizacion_auto')

CLIENTES = [('Andrés Rojas', '3104567890', None), ('Laura Gómez', '3001234567', None),
            ('Camila Torres', '3157778899', 'Comercializadora Delta S.A.S.'),
            ('Juan Pablo Díaz', '3209876543', 'Inversiones Montaña S.A.S.'),
            ('Valentina Ruiz', '3012223344', None), ('Felipe Castro', '3186665544', 'Grupo Horizonte S.A.S.')]
SALUDOS = ['Buenas tardes', 'Hola, buen día', 'Buenas', 'Buenos días, ¿cómo están?']
PIDE = ['necesito {c} {d}', 'me cotizan {c} {d}', 'quiero {c} {d}', '¿cuánto me salen {c} {d}?', 'serían {c} {d}']
# (lo que dice el cliente, lo que responde el negocio o None, la condición o la duda que queda)
CONDICIONES = [
    ('Lo necesito antes del 30 de este mes', None, ('condicion', 'El cliente lo necesita antes del 30 de este mes.')),
    ('¿Puedo pagar la mitad al inicio y la otra al terminar?', 'Sí, claro',
     ('condicion', 'Anticipo del 50 % y el saldo al terminar.')),
    ('Necesito factura electrónica a nombre de la empresa', 'Con gusto',
     ('condicion', 'El cliente necesita factura electrónica a nombre de su empresa.')),
    ('¿Eso incluye el transporte?', 'Le confirmo en la cotización',
     ('duda', '¿El transporte o desplazamiento va incluido o se cobra aparte?')),
    ('Es para un local en el centro', None, ('duda', '¿Cuál es la dirección exacta del sitio?')),
]
DUDAS_PRODUCTO = '¿Tiene alguna marca o referencia preferida?'
DUDAS_SERVICIO = '¿Qué día y en qué horario se puede hacer el trabajo?'


def _coloquial(descripcion):
    """Cómo lo escribe el cliente en el chat: sin mayúscula inicial y sin paréntesis."""
    t = descripcion.split('(')[0].strip()
    return t[0].lower() + t[1:]


def escenario(i, negocio, ciudad, items, variante):
    k = i * 2 + variante
    nombre, telefono, empresa = CLIENTES[k % len(CLIENTES)]
    dice, responde, (clase, texto_condicion) = CONDICIONES[k % len(CONDICIONES)]
    con_catalogo = variante == 1
    con_previa = variante == 1 and i % 2 == 0
    exportado = k % 3 == 0                         # chat exportado (.txt) en vez de captura
    lineas = []

    def msg(quien, texto):
        if exportado:
            lineas.append(f'17/10/26, 10:{len(lineas):02d} - {nombre if quien == "Cliente" else negocio}: {texto}')
        else:
            lineas.append(f'{quien}: {texto}')

    if not exportado:
        lineas.append(f'Contacto: {nombre}')         # el nombre que se ve arriba del chat
    msg('Cliente', f'{SALUDOS[k % len(SALUDOS)]}, me llamo {nombre.split()[0]}' + (f', de {empresa}' if empresa else '')
        + f'. Les escribo desde {ciudad}')
    for n, (cantidad, descripcion, _iva) in enumerate(items):
        pedido = PIDE[(k + n) % len(PIDE)].format(c=cantidad, d=_coloquial(descripcion))
        msg('Cliente', ('y también ' if n else '') + pedido)
    msg('Negocio', 'Con gusto, ya le preparo la cotización')
    msg('Cliente', dice)
    if responde:
        msg('Negocio', responde)
    lectura = [{'nombre': 'Chat de WhatsApp.txt' if exportado else 'captura_whatsapp.png',
                'tipo': 'texto' if exportado else 'imagen', 'texto': '\n'.join(lineas)}]

    previa = {}
    if con_previa:
        cantidad, descripcion, _ = items[0]
        precio = 45000 + 5000 * (i % 9)
        previa = {'descripcion': descripcion, 'precio': precio}
        lectura.append({'nombre': f'Cotizacion_{100 + i}.pdf', 'tipo': 'pdf', 'texto': (
            f'[Página 1]\nCOTIZACIÓN No. {100 + i}\n{negocio}\nCliente: {empresa or nombre}\n'
            f'Descripción Cant. Precio unit.\n{descripcion} 1 ${precio:,.0f}\nTOTAL ${precio:,.0f}'.replace(',', '.'))})
    relacionados = []
    if con_catalogo:
        relacionados = [{'nombre': d, 'precio': None if previa.get('descripcion') == d else 30000 + 10000 * n}
                        for n, (_, d, _) in enumerate(items)]
    cliente_ideal = {'nombre': empresa or nombre, 'telefono': '', 'ciudad': ciudad, 'documento': '', 'direccion': ''}
    salida_items = []
    for n, (cantidad, descripcion, iva) in enumerate(items):
        de_previa = previa.get('descripcion') == descripcion
        salida_items.append({
            'descripcion': descripcion if (con_catalogo or de_previa) else _coloquial(descripcion)[0].upper() + _coloquial(descripcion)[1:],
            'cantidad': cantidad,
            'tipo': 'servicio' if nc.es_servicio(descripcion) else 'producto',
            'iva': iva,
            'precio_referencia': previa['precio'] if de_previa else None,
            'fuente_precio': f'Cotización {100 + i} (PDF)' if de_previa else '',
            'costo': None,
            'por_que': f'«{PIDE[(k + n) % len(PIDE)].format(c=cantidad, d=_coloquial(descripcion))}»',
            'sugerido': False,
        })
    dudas = [texto_condicion] if clase == 'duda' else []
    dudas.append(DUDAS_SERVICIO if any(x['tipo'] == 'servicio' for x in salida_items) else DUDAS_PRODUCTO)
    respuesta = {
        'cliente': cliente_ideal,
        'resumen': f'{empresa or nombre} pide ' + ', '.join(
            f'{c} × {_coloquial(d)}' for c, d, _ in items) + f' en {ciudad}.',
        'items': salida_items,
        'condiciones': [texto_condicion] if clase == 'condicion' else [],
        'dudas': dudas,
    }
    return {'negocio': negocio, 'lectura': lectura, 'relacionados': relacionados, 'respuesta': respuesta}


def escenarios():
    return [escenario(i, negocio, ciudad, items, v)
            for i, (negocio, ciudad, items) in enumerate(NEGOCIOS) for v in (0, 1)]


def ejemplo(e):
    return {'messages': [
        {'role': 'system', 'content': auto.SISTEMA_PLAN.format(negocio=e['negocio'])},
        {'role': 'user', 'content': auto.peticion_plan(e['lectura'], e['relacionados'])},
        {'role': 'assistant', 'content': json.dumps(e['respuesta'], ensure_ascii=False)},
    ]}


def main():
    os.makedirs(SALIDA, exist_ok=True)
    lista = escenarios()
    with open(os.path.join(SALIDA, 'cotizacion_auto_ft.jsonl'), 'w', encoding='utf-8', newline='\n') as f:
        for e in lista:
            f.write(json.dumps(ejemplo(e), ensure_ascii=False) + '\n')
    banco = [{'negocio': e['negocio'], 'lectura': e['lectura'], 'relacionados': e['relacionados'],
              'esperado': {'items': [(x['descripcion'], x['cantidad']) for x in e['respuesta']['items']],
                           'precio_referencia': [x['precio_referencia'] for x in e['respuesta']['items']],
                           'condiciones': e['respuesta']['condiciones'], 'dudas': len(e['respuesta']['dudas'])}}
             for e in lista]
    with open(os.path.join(SALIDA, 'banco_cotizacion_auto.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(banco, f, ensure_ascii=False, indent=1)
    print(f'{len(lista)} ejemplos → {SALIDA}')
    print('Con cotización anterior en PDF:', sum(1 for e in lista if len(e['lectura']) > 1))
    print('Con catálogo:', sum(1 for e in lista if e['relacionados']))
    print('Chat exportado (.txt):', sum(1 for e in lista if e['lectura'][0]['tipo'] == 'texto'))


if __name__ == '__main__':
    main()
