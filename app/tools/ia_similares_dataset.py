"""Banco de 100 ejemplos para afinar (fine-tuning) la IA que, ANTES de crear un producto,
lo compara con los productos parecidos que ya tiene la tienda.

Nace de un catálogo real de panadería y minimercado (582 productos), donde se ven los tres
casos que confunden: el mismo producto escrito de dos formas («TRIDENT INDIVIDUAL» y
«TRAIDENPEQUEÑO»), la misma marca en dos presentaciones con el mismo nombre («DIANA
ACEITE» a dos precios) y el mismo tipo de producto de marcas distintas («CIELO AGUA»,
«BRISA AGUA», «GLACIAL AGUA»). Los IDs, precios y códigos de este banco son inventados;
las marcas son productos de consumo conocidos en Colombia.

La IA recibe el producto que se quiere crear y los parecidos que encontró Python, y
responde SOLO un JSON con la decisión. Nunca modifica nada: solo aconseja; la persona
confirma.

  duplicado  misma marca, mismo producto y misma presentación (o el mismo código de
             barras): no crear otro; decir cuál es (producto_id).
  variante   misma marca y producto, otra presentación, tamaño o sabor: sí se crea, con
             la presentación en el nombre para no confundirlos (nombre_sugerido).
  distinto   otra marca u otro producto: se crea normal.
  aclarar    no se puede saber (no dijo la presentación y hay varias): preguntar.

Uso:
    python tools/ia_similares_dataset.py      # escribe tools/ia_datasets/productos_similares/
"""
import json
import os

SALIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ia_datasets', 'productos_similares')

SISTEMA = (
    'Eres el asistente de inventario de «{negocio}», una tienda en Colombia. Antes de crear un producto lo '
    'comparas con los PRODUCTOS PARECIDOS que ya existen en su catálogo y decides si es nuevo. No modificas '
    'nada: solo aconsejas y la persona confirma.\n'
    'Reglas:\n'
    '1. «duplicado»: misma marca, mismo producto y misma presentación (tamaño, peso, cantidad o sabor), '
    'aunque esté escrito distinto (mayúsculas, abreviaturas, errores de tecleo: «traident» es Trident, '
    '«1L» es 1000 ML). Si el código de barras es el mismo, siempre es duplicado. Da el producto_id.\n'
    '2. «variante»: misma marca y mismo producto pero otra presentación, tamaño o sabor. Se crea, con la '
    'presentación en el nombre para no confundirlo: da nombre_sugerido con el estilo del catálogo.\n'
    '3. «distinto»: otra marca, u otro producto aunque se parezca (Cielo y Brisa son marcas distintas de '
    'agua). Se crea normal.\n'
    '4. «aclarar»: no se puede saber, por ejemplo si no dijo la presentación y hay varias. Pregunta corta '
    'con las opciones que existen.\n'
    '5. No inventes tamaños, marcas ni códigos: usa solo lo que dijo la persona y lo que trae el catálogo.\n'
    'Responde SOLO un JSON: {{"decision":"duplicado|variante|distinto|aclarar","producto_id":entero o null,'
    '"nombre_sugerido":texto o null,"motivo":"una frase","pregunta":texto o null}}.'
)

NEGOCIOS = ['Panadería La Espiga', 'Minimercado El Ahorro', 'Panadería y Pastelería Dulce Hogar',
            'Tienda Don Pepe', 'Supermercado La Economía']

# (marca, producto, categoría, presentaciones existentes [(presentación, precio)], presentación nueva,
#  cómo la escribe la persona (duplicado), otra marca del mismo producto, nota de equivalencia)
FAMILIAS = [
    ('DIANA', 'ACEITE', 'ACEITE', [('500 ML', 3300), ('1000 ML', 6000)], '3000 ML', 'aceite diana 1L', 'PREMIER', '1L = 1000 ML'),
    ('CIELO', 'AGUA', 'AGUAS', [('600 ML', 1500), ('1 L', 2500)], '5 L', 'agua cielo 600ml', 'BRISA', ''),
    ('AGUILA ROJA', 'CAFÉ', 'CAFÉ GRANO', [('125 GR', 2800), ('250 GR', 7600)], '500 GR', 'cafe aguila roja 250 gr', 'SELLO ROJO', ''),
    ('TRIDENT', 'CHICLE', 'CHICLES', [('X 5 YERBABUENA', 2000), ('X 5 SANDIA', 2000)], 'X 5 MENTA', 'traident x5 yerbabuena', 'CHICLETS', 'traident = Trident'),
    ('DOVE', 'ACONDICIONADOR', 'ACONDICIONADOR', [('HIDRATACION SOBRE 18 ML', 1400), ('RECONSTRUCCION SOBRE 18 ML', 1400)], 'HIDRATACION 400 ML', 'acondicionador dove hidratacion sobre', 'PANTENE', ''),
    ('COLGATE', 'CREMA DENTAL TRIPLE ACCION', 'ASEO', [('75 ML', 5500), ('150 ML', 9800)], '50 ML', 'crema colgate triple accion 75ml', 'FORTIDENT', ''),
    ('REXONA', 'DESODORANTE', 'ASEO', [('AVENA', 4400), ('BAMBOO Y ALOE', 4400)], 'CLINICAL', 'desodorante rexona avena', 'SPEED STICK', ''),
    ('KELLOGGS', 'ZUCARITAS', 'CEREAL', [('30 GR', 1700), ('300 GR', 9900)], '600 GR', 'zucaritas kelloggs 30g', 'NESTLE', ''),
    ('COCA-COLA', 'GASEOSA', 'GASEOSAS', [('400 ML', 3000), ('1.5 L', 6500)], '3 L', 'coca cola 400', 'POSTOBON', ''),
    ('ALPINA', 'LECHE ENTERA', 'LACTEOS', [('1 L', 4200), ('200 ML', 1500)], '1.1 L BOLSA', 'leche alpina entera litro', 'COLANTA', 'litro = 1 L'),
    ('BIMBO', 'PAN TAJADO', 'PANADERIA', [('600 GR', 7900)], '350 GR', 'pan tajado bimbo grande 600g', 'COMAPAN', ''),
    ('KIKES', 'HUEVOS AA', 'HUEVOS', [('X 30', 18000), ('X 12', 7800)], 'X 6', 'huevos kikes aa por 30', 'SANTA REYES', ''),
    ('ROA', 'ARROZ', 'GRANOS', [('500 GR', 2600), ('1000 GR', 5000)], '5000 GR', 'arroz roa kilo', 'DIANA', 'kilo = 1000 GR'),
    ('MANUELITA', 'AZUCAR', 'GRANOS', [('1 KG', 4800)], '500 GR', 'azucar manuelita 1kg', 'RIOPAILA', ''),
    ('FAMILIA', 'PAPEL HIGIENICO', 'ASEO', [('EXPERT X 4', 2900), ('GREEN X 4', 2000)], 'EXPERT X 12', 'papel familia expert x4', 'SCOTT', ''),
    ('PROTEX', 'JABON', 'ASEO', [('HERBAL 110 GR', 4400), ('LIMPIEZA PROFUNDA 110 GR', 4400)], 'AVENA 110 GR', 'jabon protex herbal', 'DOVE', ''),
    ('NORAVER', 'GRIPA', 'ANALGESICO', [('CAPSULA', 2200)], 'NOCHE', 'noraver gripa capsula', 'DOLEX', ''),
    ('AROMA', 'CAFÉ INSTANTANEO', 'CAFÉ', [('40 GR', 2500), ('85 GR', 4900)], '170 GR', 'aroma cafe 40g', 'COLCAFE', ''),
    ('FESTIVAL', 'GALLETAS', 'GALLETAS', [('CHOCOLATE', 1200), ('FRESA', 1200)], 'LIMON', 'galletas festival de chocolate', 'OREO', ''),
    ('ALPINA', 'YOGURT', 'LACTEOS', [('FRESA 200 GR', 2700), ('MELOCOTON 200 GR', 2700)], 'MORA 1000 GR', 'yogurt alpina fresa 200', 'COLANTA', ''),
    ('STARLITE', 'BOMBILLO LED', 'BOMBILLO', [('9 W', 3500), ('12 W', 4900)], '20 W', 'bombillo starlite led 9w', 'PHILIPS', ''),
    ('AXION', 'LAVALOZA', 'ASEO', [('DISCO 235 GR', 2200), ('CREMA 450 GR', 5900)], 'LIQUIDO 640 ML', 'axion disco', 'LOZACREM', ''),
    ('JET', 'CHOCOLATINA', 'CHOCOLATE', [('12 GR', 1000), ('CON LECHE 24 GR', 2000)], 'COOKIES AND CREAM 50 GR', 'chocolatina jet pequeña 12 gr', 'BIANCHI', ''),
    ('POKER', 'CERVEZA', 'CERVEZAS', [('LATA 330 ML', 3200), ('BOTELLA 330 ML', 3000)], 'LATA 473 ML', 'cerveza poker lata', 'AGUILA', ''),
    ('LA LECHERA', 'LECHE CONDENSADA', 'ADEREZOS', [('420 GR', 13000), ('100 GR', 4000)], 'DOYPACK 200 GR', 'la lechera grande 420gr', 'NESTLE', ''),
]


def catalogo(i, familia):
    marca, producto, categoria, presentaciones = familia[:4]
    salida = []
    for n, (pres, precio) in enumerate(presentaciones):
        salida.append({'id': 100 + i * 10 + n, 'nombre': f'{marca} {producto} {pres}',
                       'referencia': f'77{i:02d}{n:02d}{(i * 7 + n) % 10}{"0" * 6}', 'precio': precio,
                       'categoria': categoria})
    return salida


def lineas(cat):
    return '\n'.join(f'- ID {p["id"]} · {p["nombre"]} · ref {p["referencia"]} · ${p["precio"]:,} · {p["categoria"]}'
                     .replace(',', '.') for p in cat)


def peticion(nuevo, cat):
    return (f'PRODUCTO QUE SE QUIERE CREAR: {json.dumps(nuevo, ensure_ascii=False)}\n'
            f'PRODUCTOS PARECIDOS EN EL CATÁLOGO:\n{lineas(cat)}\nResponde solo el JSON.')


def respuesta(decision, producto_id=None, nombre_sugerido=None, motivo='', pregunta=None):
    return {'decision': decision, 'producto_id': producto_id, 'nombre_sugerido': nombre_sugerido,
            'motivo': motivo, 'pregunta': pregunta}


# Presentación que la persona repite en el caso «duplicado» (índice en la familia).
DUPLICA = {0: 1, 2: 1, 12: 1}


def casos():
    salida = []
    for i, fam in enumerate(FAMILIAS):
        marca, producto, categoria, presentaciones, nueva, escrito, otra, equivalencia = fam
        cat = catalogo(i, fam)
        negocio = NEGOCIOS[i % len(NEGOCIOS)]
        duplicada = cat[DUPLICA.get(i, 0)]
        # Duplicado: la misma presentación, escrita como la escribe la gente.
        motivo = f'Ya existe {duplicada["nombre"]}: misma marca, mismo producto y misma presentación'
        if equivalencia:
            motivo += f' ({equivalencia})'
        salida.append((negocio, {'nombre': escrito, 'precio': duplicada['precio']}, cat,
                       respuesta('duplicado', duplicada['id'], None, motivo + '.')))
        if i % 2 == 1 and len(presentaciones) >= 2:
            # Aclarar: no dijo la presentación y la marca tiene varias.
            opciones = ' o '.join(f'{p["nombre"]} (${p["precio"]:,})'.replace(',', '.') for p in cat)
            salida.append((negocio, {'nombre': f'{marca.title()} {producto.lower()}'}, cat,
                           respuesta('aclarar', None, None,
                                     f'{marca} {producto} existe en varias presentaciones y no dijiste cuál.',
                                     f'¿Es {opciones}, o una presentación nueva?')))
        else:
            # Duplicado por código de barras, aunque el nombre no se parezca.
            salida.append((negocio, {'nombre': f'{producto.lower()} {marca.title()}',
                                     'referencia': cat[0]['referencia'], 'precio': cat[0]['precio']}, cat,
                           respuesta('duplicado', cat[0]['id'], None,
                                     f'El código de barras {cat[0]["referencia"]} ya es de {cat[0]["nombre"]}.')))
        # Variante: misma marca y producto, otra presentación.
        salida.append((negocio, {'nombre': f'{producto.lower()} {marca.lower()} {nueva.lower()}',
                                 'categoria': categoria}, cat,
                       respuesta('variante', None, f'{marca} {producto} {nueva}',
                                 f'Misma marca y producto que {cat[0]["nombre"]}, pero otra presentación ({nueva}): '
                                 'es un producto aparte.')))
        # Distinto: otra marca del mismo producto.
        salida.append((negocio, {'nombre': f'{producto.lower()} {otra.lower()} {presentaciones[0][0].lower()}',
                                 'categoria': categoria}, cat,
                       respuesta('distinto', None, None,
                                 f'{otra} es otra marca: no es el mismo producto que {marca}.')))
    return salida


def main():
    os.makedirs(SALIDA, exist_ok=True)
    lista = casos()
    with open(os.path.join(SALIDA, 'productos_similares_ft.jsonl'), 'w', encoding='utf-8', newline='\n') as f:
        for negocio, nuevo, cat, resp in lista:
            f.write(json.dumps({'messages': [
                {'role': 'system', 'content': SISTEMA.format(negocio=negocio)},
                {'role': 'user', 'content': peticion(nuevo, cat)},
                {'role': 'assistant', 'content': json.dumps(resp, ensure_ascii=False)},
            ]}, ensure_ascii=False) + '\n')
    with open(os.path.join(SALIDA, 'banco_productos_similares.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump([{'negocio': n, 'nuevo': nv, 'catalogo': c, 'esperado': r} for n, nv, c, r in lista],
                  f, ensure_ascii=False, indent=1)
    conteo = {}
    for *_, r in lista:
        conteo[r['decision']] = conteo.get(r['decision'], 0) + 1
    print(f'{len(lista)} ejemplos → {SALIDA}', conteo)


if __name__ == '__main__':
    main()
