"""Servicio Técnico: la ficha técnica del equipo en PDF («FICHA TECNICA»).

Es el formato que el taller entrega al cliente (acta de entrega): encabezado
con el código, la fecha y el próximo mantenimiento; «EQUIPO ASIGNADO A …»;
descripción general con fotos; características globales; vida útil con sus
recomendaciones; datos del fabricante; descripción del problema y detalle
técnico de requerimientos.

- Ficha ROJA: el equipo presenta algún inconveniente. Ficha AZUL: en buen
  estado. Las filas que muestran el problema (p. ej. la RAM) van en rojo.
- `armar`     junta lo que va en la ficha: lo guardado en `st_equipos.ficha`
              y, donde no hay nada, lo que dicen los datos del equipo.
- `pdf`       la dibuja con reportlab, en una sola hoja.
- `borrador`  propone los textos con reglas fijas (sin IA); la IA los redacta
              con el estilo de las fichas del taller (`servicio_tecnico_ia`).
- `leer_pdf`  reconoce este mismo formato en un PDF (lo usa el importador).
"""

import io
import re
import unicodedata
from datetime import date
from xml.sax.saxutils import escape

from database import get_db_cursor
from services import servicio_tecnico_service as st
from services import servicio_tecnico_tipos as tipos
from services.servicio_tecnico_service import ErrorServicio

ESTADOS = (('bueno', 'En buen estado (ficha azul)'), ('inconveniente', 'Presenta inconvenientes (ficha roja)'))
# Filas de «CARACTERÍSTICAS GLOBALES» de un computador, en el orden de la ficha.
FILAS_PC = ('Sistema Operativo', 'Fabricante del Sistema', 'Modelo', 'Serial', 'Nombre de Usuario', 'Tipo de sistema',
            'Procesador', 'Memoria RAM', 'Memoria física disponible', 'Placa Base', 'Zona Horaria',
            'Unidad de Disco', 'BIOS', 'Directorios del Sistema', 'Memoria virtual')
FOTOS_EN_FICHA = 3
_MESES = ('ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic')
# Colores del formato (los mismos de las fichas del taller).
ROJO = '#FF4F4F'            # barras y etiquetas de la ficha roja
ROJO_TEXTO = '#D92B2B'      # filas resaltadas
AZUL = '#B4C6E7'            # encabezado y barras de la ficha azul
AZUL_TEXTO = '#1F3864'
GRIS = '#7F7F7F'            # barra «EQUIPO ASIGNADO A …»
ENLACE = '#0563C1'
FABRICANTES = {'hp': 'HP (Hewlett-Packard)', 'hewlett packard': 'HP (Hewlett-Packard)', 'lenovo': 'LENOVO',
               'dell': 'DELL', 'asus': 'ASUS', 'acer': 'ACER', 'apple': 'Apple', 'samsung': 'Samsung',
               'msi': 'MSI', 'toshiba': 'Toshiba', 'huawei': 'Huawei', 'xiaomi': 'Xiaomi', 'lg': 'LG'}
SOPORTE = {'hp': 'https://support.hp.com/co-es/search?q={q}', 'lenovo': 'https://pcsupport.lenovo.com/co/es/search?query={q}',
           'dell': 'https://www.dell.com/support/search/es-co#q={q}', 'asus': 'https://www.asus.com/co/searchresult?searchType=support&searchKey={q}',
           'acer': 'https://www.acer.com/co-es/support/search?search={q}', 'apple': 'https://support.apple.com/es-lamr/search?q={q}',
           'samsung': 'https://www.samsung.com/co/search/?searchvalue={q}'}


def _norm(texto):
    t = unicodedata.normalize('NFD', str(texto or '').lower())
    t = ''.join(ch for ch in t if unicodedata.category(ch) != 'Mn')
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', t).split())


def _texto(valor, largo):
    return ' '.join(str(valor or '').split())[:largo] or None


def fecha_corta(f):
    """5-ago-26, como en las fichas del taller."""
    return f'{f.day}-{_MESES[f.month - 1]}-{f.year % 100:02d}' if f else '—'


def leer_fecha(texto):
    """«5-ago-26», «28-07-2026», «28/07/2026» o «2026-07-28» → date (o None)."""
    t = _norm(texto).replace(' ', '-')
    for patron, orden in ((r'(\d{4})-(\d{1,2})-(\d{1,2})', 'amd'), (r'(\d{1,2})-(\d{1,2})-(\d{2,4})', 'dma'),
                          (r'(\d{1,2})-([a-z]{3})[a-z]*-(\d{2,4})', 'dMa')):
        m = re.search(patron, t)
        if not m:
            continue
        try:
            if orden == 'amd':
                a, mes, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            elif orden == 'dma':
                d, mes, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
            else:
                if m.group(2) not in _MESES and m.group(2) != 'set':
                    continue
                d, mes, a = int(m.group(1)), (_MESES.index(m.group(2)) + 1) if m.group(2) != 'set' else 9, int(m.group(3))
            a += 2000 if a < 100 else 0
            return date(a, mes, d)
        except ValueError:
            continue
    return None


# ── Qué va en la ficha ──────────────────────────────────────────
def _ram_auto(e):
    extras = e.get('extras') or {}
    ram = e.get('ram') or ''
    if ram and extras.get('ram_ranuras_total'):
        libres = extras.get('ram_ranuras_libres')
        ram += f" - {extras['ram_ranuras_total']} ranuras" + (
            f', {libres} libre{"s" if str(libres) != "1" else ""}' if libres not in (None, '') else '')
    return ram


def filas_base(e):
    """[(etiqueta, valor sacado de los datos del equipo)] en el orden de la ficha."""
    extras = e.get('extras') or {}
    if e.get('tipo') in ('computador', 'portatil'):
        disco = e.get('almacenamiento') or ''
        if extras.get('tipo_disco') and _norm(extras['tipo_disco']) not in _norm(disco):
            disco = f"{disco} ({extras['tipo_disco']})" if disco else extras['tipo_disco']
        auto = {'Sistema Operativo': e.get('sistema_operativo'), 'Fabricante del Sistema': e.get('marca'),
                'Modelo': e.get('modelo'), 'Serial': e.get('serial'), 'Procesador': e.get('procesador'),
                'Memoria RAM': _ram_auto(e), 'Placa Base': extras.get('board'), 'Unidad de Disco': disco}
        return [(etq, auto.get(etq) or '') for etq in FILAS_PC]
    filas = [('Fabricante', e.get('marca')), ('Modelo', e.get('modelo'))]
    for c in tipos.columnas(e.get('tipo')):
        if c not in ('marca', 'modelo'):
            filas.append((tipos.ETIQUETAS_COMUNES[c], e.get(c)))
    for clave, etiqueta, tipo_input, _op in tipos.campos_extra(e.get('tipo')):
        valor = extras.get(clave)
        if tipo_input == 'si_no' and valor:
            valor = 'Sí' if valor == 'si' else 'No'
        filas.append((etiqueta, valor))
    return [(etq, v or '') for etq, v in filas]


def _cliente(equipo_id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT c.nombre, c.empresa FROM st_equipos e LEFT JOIN crm_contactos c ON c.id = e.crm_contacto_id
                       WHERE e.id = %s""", (equipo_id,))
        fila = cur.fetchone()
        cur.execute('SELECT MAX(fecha) AS f FROM st_mantenimientos WHERE equipo_id = %s AND activo', (equipo_id,))
        ultimo = cur.fetchone()['f']
    return (dict(fila) if fila else {}), ultimo


def fotos_de_la_ficha(equipo_id, elegidas=None):
    """Las fotos que salen en la ficha: las escogidas o las primeras (máx. 3)."""
    fotos = st.fotos_de_equipo(equipo_id)
    if elegidas:
        por_id = {f['id']: f for f in fotos}
        escogidas = [por_id[i] for i in elegidas if i in por_id]
        if escogidas:
            return escogidas[:FOTOS_EN_FICHA]
    orden = {'ficha': 0, 'etiqueta': 2, 'recepcion': 1, 'entrega': 3, 'reparacion': 4}
    return sorted(fotos, key=lambda f: (orden.get(f['momento'], 5), -f['id']))[:FOTOS_EN_FICHA]


def armar(equipo_id):
    """Todo lo que va en la ficha (para el PDF y la pantalla de edición)."""
    equipo = st.obtener_equipo(equipo_id)
    if not equipo:
        raise ErrorServicio('El equipo no existe.')
    ficha = equipo.get('ficha') or {}
    cliente, ultimo = _cliente(equipo_id)
    propias = ficha.get('filas') or {}
    destacar = set(ficha.get('destacar') or [])
    filas = []
    for etq, auto in filas_base(equipo):
        valor = (propias.get(etq) or '').strip() or (auto or '').strip()
        filas.append({'etiqueta': etq, 'valor': valor, 'propio': bool((propias.get(etq) or '').strip()),
                      'auto': auto or '', 'destacar': etq in destacar})
    for etq, valor in propias.items():            # filas que trajo un documento y no están en la lista
        if etq not in {f['etiqueta'] for f in filas} and (valor or '').strip():
            filas.append({'etiqueta': etq, 'valor': valor.strip(), 'propio': True, 'auto': '',
                          'destacar': etq in destacar})
    fecha = leer_fecha(ficha.get('fecha')) if ficha.get('fecha') else (ultimo or date.today())
    asignado = (ficha.get('asignado_a') or '').strip() or cliente.get('nombre') or ''
    empresa = (ficha.get('empresa') or '').strip()
    if not empresa and ficha.get('asignado_a') and cliente.get('nombre') and \
            _norm(cliente['nombre']) != _norm(ficha['asignado_a']):
        empresa = cliente['nombre']
    if not empresa and cliente.get('empresa') and _norm(cliente['empresa']) != _norm(asignado):
        empresa = cliente['empresa']
    marca = equipo.get('marca') or ''
    detalle = ficha.get('fabricante_detalle') or ' / '.join(
        x for x in (equipo.get('modelo'), (f"Placa base {(equipo.get('extras') or {}).get('board')}"
                                           if (equipo.get('extras') or {}).get('board') else None)) if x)
    from services.servicio_tecnico_mensajes import datos_negocio
    return {
        'equipo': equipo, 'equipo_id': equipo_id, 'codigo': equipo.get('ficha_codigo'),
        'version': ficha.get('version') or 1, 'fecha': fecha, 'proximo': equipo.get('mant_proximo'),
        'estado': ficha.get('estado') or 'bueno', 'asignado_a': asignado, 'empresa': empresa,
        'titulo': ('EQUIPO ASIGNADO A ' + ' - '.join(x for x in (asignado, empresa) if x)).upper(),
        'descripcion': ficha.get('descripcion') or equipo.get('resumen_ia') or '', 'filas': filas,
        'vida_util': ficha.get('vida_util') or '', 'recomendaciones': ficha.get('recomendaciones') or [],
        'fabricante': ficha.get('fabricante') or FABRICANTES.get(_norm(marca), marca.upper() if marca else ''),
        'fabricante_detalle': detalle, 'fabricante_url': url_soporte(marca, equipo.get('modelo')),
        'problema': ficha.get('problema') or '', 'requerimientos': ficha.get('requerimientos') or '',
        'fotos': fotos_de_la_ficha(equipo_id, ficha.get('fotos')), 'fotos_elegidas': ficha.get('fotos') or [],
        'negocio': datos_negocio().get('negocio') or '', 'guardada': bool(ficha),
    }


def url_soporte(marca, modelo):
    from urllib.parse import quote_plus
    patron = SOPORTE.get(_norm(marca))
    consulta = quote_plus(' '.join(x for x in (marca, modelo) if x))
    if patron:
        return patron.format(q=quote_plus(modelo or marca or ''))
    return f'https://www.google.com/search?q={consulta}+soporte' if consulta else ''


def nombre_pdf(datos):
    """«ANA PÉREZ - HP Laptop 15-gw0 - Ult Mtto 2026-08-05.pdf», como los del taller."""
    e = datos['equipo']
    modelo = ' '.join(x for x in (e.get('marca') if not _norm(e.get('modelo') or '').startswith(_norm(e.get('marca') or '-'))
                                  else None, e.get('modelo')) if x) or tipos.nombre(e.get('tipo'))
    partes = [datos['asignado_a'] or datos['empresa'] or 'Equipo', modelo]
    if datos['fecha']:
        partes.append(f"Ult Mtto {datos['fecha'].isoformat()}")
    return st.nombre_archivo(' - '.join(p for p in partes if p) + '.pdf')


# ── Dibujar el PDF ──────────────────────────────────────────────
def pdf(datos):
    """Bytes del PDF de la ficha (una hoja A4)."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image, KeepInFrame, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    rojo = datos['estado'] == 'inconveniente'
    barra = colors.HexColor(ROJO if rojo else AZUL)
    barra_texto = colors.white if rojo else colors.HexColor(AZUL_TEXTO)
    negro = colors.HexColor('#1A1A1A')
    margen = 34
    ancho = A4[0] - 2 * margen
    salida = io.BytesIO()
    doc = SimpleDocTemplate(salida, pagesize=A4, leftMargin=margen, rightMargin=margen, topMargin=26, bottomMargin=26,
                            title=f"Ficha técnica {datos['codigo'] or ''}".strip(), author=datos['negocio'],
                            subject=datos['titulo'])

    def estilo(nombre, tam=8.2, negrita=True, alin=TA_CENTER, color=negro, interlinea=None):
        return ParagraphStyle(nombre, fontName='Helvetica-Bold' if negrita else 'Helvetica', fontSize=tam,
                              leading=interlinea or tam * 1.22, alignment=alin, textColor=color)
    s_celda = estilo('celda')
    s_titulo = estilo('titulo', 9.5, color=colors.white)
    s_barra = estilo('barra', 8.5, color=barra_texto)
    s_parrafo = estilo('parrafo', 8.4, alin=TA_LEFT, interlinea=10.6)
    s_valor = estilo('valor', 8)
    s_valor_rojo = estilo('valor_rojo', 8, color=colors.HexColor(ROJO_TEXTO))
    s_etiqueta = estilo('etiqueta', 8, negrita=False)
    s_etiqueta_roja = estilo('etiqueta_roja', 8, negrita=False, color=colors.HexColor(ROJO_TEXTO))
    s_lateral = estilo('lateral', 8, alin=TA_LEFT, color=barra_texto)
    s_check = estilo('check', 8.2, alin=TA_LEFT, interlinea=10.2)

    def p(texto, s=s_celda):
        return Paragraph(escape(str(texto or '')).replace('\n', '<br/>'), s)

    rejilla = colors.HexColor('#404040')
    # 1. Encabezado: logo, negocio, «FICHA TECNICA», código, fechas y versión.
    logo = _logo(ancho * 0.24 - 10, 62, Image, ImageReader)
    encabezado = Table([
        [logo or p(datos['negocio']), p(datos['negocio']), p('CODIGO'),
         p(datos['codigo'] or 'Sin código', s_celda if len(datos['codigo'] or '') <= 18 else estilo('codigo', 6.6))],
        ['', '', p('FECHA'), p(fecha_corta(datos['fecha']))],
        ['', '', p('FECHA PROXIMO MANTENIMIENTO'), p(fecha_corta(datos['proximo']))],
        ['', p('FICHA TECNICA'), p('VERSION'), p(datos['version'])],
    ], colWidths=[ancho * 0.24, ancho * 0.38, ancho * 0.19, ancho * 0.19], rowHeights=[19, 19, 24, 18])
    encabezado.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(AZUL)),
        ('GRID', (1, 0), (-1, -1), 0.6, rejilla), ('BOX', (0, 0), (-1, -1), 0.9, rejilla),
        ('SPAN', (0, 0), (0, 3)), ('SPAN', (1, 0), (1, 2)),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('VALIGN', (1, 0), (1, 2), 'TOP'),
        ('ALIGN', (0, 0), (0, 3), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 2), ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    titulo = Table([[p(datos['titulo'], s_titulo)]], colWidths=[ancho])
    titulo.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(GRIS)),
                                ('BOX', (0, 0), (-1, -1), 0.9, rejilla),
                                ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]))

    # 2. Descripción general y fotos.
    ancho_fotos = ancho * 0.52
    fotos = _fotos(datos['fotos'], ancho_fotos - 8, 104, Image, ImageReader)
    fila_fotos = Table([fotos], colWidths=[(ancho_fotos - 8) / max(len(fotos), 1)] * max(len(fotos), 1)) if fotos \
        else p('Sin fotos del equipo.', s_etiqueta)
    descripcion = Table([
        [p('DESCRIPCIÓN GENERAL DEL EQUIPO', s_barra), p('REGISTRO FOTOGRÁFICO', s_barra)],
        [p(datos['descripcion'] or 'Sin descripción.', s_parrafo), fila_fotos],
    ], colWidths=[ancho - ancho_fotos, ancho_fotos])
    descripcion.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), barra), ('GRID', (0, 0), (-1, -1), 0.6, rejilla),
        ('BOX', (0, 0), (-1, -1), 0.9, rejilla), ('VALIGN', (0, 1), (0, 1), 'TOP'), ('VALIGN', (1, 1), (1, 1), 'MIDDLE'),
        ('ALIGN', (1, 1), (1, 1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))

    # 3. Características globales (solo las filas con dato; las del problema en rojo).
    filas = [[p('CARACTERÍSTICAS GLOBALES', s_barra), '']]
    estilos = [('SPAN', (0, 0), (1, 0)), ('BACKGROUND', (0, 0), (-1, 0), barra),
               ('BOX', (0, 0), (-1, -1), 0.9, rejilla), ('LINEBELOW', (0, 0), (-1, 0), 0.6, rejilla),
               ('VALIGN', (0, 1), (-1, -1), 'MIDDLE'),
               ('TOPPADDING', (0, 0), (-1, -1), 2.2), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.2)]
    for f in datos['filas']:
        if not f['valor']:
            continue
        resaltar = f['destacar'] and rojo
        filas.append([p(f['etiqueta'], s_etiqueta_roja if resaltar else s_etiqueta),
                      p(f['valor'], s_valor_rojo if resaltar else s_valor)])
    caracteristicas = Table(filas, colWidths=[ancho * 0.42, ancho * 0.58])
    caracteristicas.setStyle(TableStyle(estilos))

    # 4. Vida útil y recomendaciones.
    vida = [p(datos['vida_util'] or 'Sin información de vida útil.', s_parrafo)]
    if datos['recomendaciones']:
        color_check = colors.HexColor(ROJO if rojo else AZUL_TEXTO)
        lista = Table([[_casilla(color_check), p(r, s_check)] for r in datos['recomendaciones']],
                      colWidths=[14, ancho - 26])
        lista.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                                   ('TOPPADDING', (0, 0), (-1, -1), 1.2), ('BOTTOMPADDING', (0, 0), (-1, -1), 1.2)]))
        vida += [Spacer(1, 3), lista]
    vida_util = Table([[p('VIDA UTIL', s_barra)], [vida]], colWidths=[ancho])
    vida_util.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), barra), ('BOX', (0, 0), (-1, -1), 0.9, rejilla),
                                   ('LINEBELOW', (0, 0), (-1, 0), 0.6, rejilla),
                                   ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 1), (-1, 1), 8)]))

    # 5. Fabricante, problema y requerimientos.
    enlace = escape(datos['fabricante_detalle'] or '')
    if datos['fabricante_url'] and enlace:
        enlace = f'<a href="{escape(datos["fabricante_url"])}" color="{ENLACE}"><u>{enlace}</u></a>'
    fabricante = [p(datos['fabricante'] or '—', s_valor), Paragraph(enlace, estilo('enlace', 7.8, False, color=colors.HexColor(ENLACE)))] \
        if enlace else [p(datos['fabricante'] or '—', s_valor)]
    final = Table([
        [p('DATOS DEL FABRICANTE', s_lateral), fabricante],
        [p('DESCRIPCION DEL PROBLEMA', s_lateral), p(datos['problema'] or 'N/A', s_valor)],
        [p('DETALLE TECNICO DE REQUERIMIENTOS', s_lateral), p(datos['requerimientos'] or 'N/A', s_valor)],
    ], colWidths=[ancho * 0.33, ancho * 0.67])
    final.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), barra), ('GRID', (0, 0), (-1, -1), 0.6, rejilla),
        ('BOX', (0, 0), (-1, -1), 0.9, rejilla), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 14),
    ]))

    contenido = [encabezado, titulo, descripcion, caracteristicas, vida_util, final]
    alto = A4[1] - 52
    doc.build([KeepInFrame(ancho, alto, content=contenido, mode='shrink', hAlign='CENTER')])
    return salida.getvalue()


def _casilla(color):
    """Casilla con el chulo (☑) dibujada: no depende de las fuentes del visor."""
    from reportlab.graphics.shapes import Drawing, PolyLine, Rect
    d = Drawing(10, 10)
    d.add(Rect(0.6, 0.6, 8.8, 8.8, strokeColor=color, fillColor=None, strokeWidth=0.9))
    d.add(PolyLine([2.2, 5.0, 4.1, 2.8, 8.0, 7.6], strokeColor=color, strokeWidth=1.4))
    return d


def _logo(ancho, alto, Image, ImageReader):
    import os

    from flask import current_app

    from helpers import logo_local_path
    try:
        ruta = logo_local_path(current_app.root_path)
        if not os.path.isfile(ruta):
            return None
        w, h = ImageReader(ruta).getSize()
        escala = min(ancho / w, alto / h)
        return Image(ruta, width=w * escala, height=h * escala)
    except Exception:  # noqa: BLE001
        return None


def _fotos(fotos, ancho_total, alto, Image, ImageReader):
    salida = []
    if not fotos:
        return salida
    ancho = ancho_total / len(fotos) - 6
    for f in fotos:
        contenido = st.foto_contenido(f['id'])
        if not contenido:
            continue
        lector = ImageReader(io.BytesIO(contenido[1]))
        w, h = lector.getSize()
        escala = min(ancho / w, alto / h)
        salida.append(Image(io.BytesIO(contenido[1]), width=w * escala, height=h * escala))
    return salida


# ── Guardar ─────────────────────────────────────────────────────
def guardar(equipo_id, datos, usuario_id=None):
    """Guarda lo que se escribió en la ficha. `datos`: dict del formulario."""
    import json
    estado = (datos.get('estado') or '').strip()
    if estado not in dict(ESTADOS):
        raise ErrorServicio('Escoge si el equipo está en buen estado o presenta inconvenientes.')
    try:
        version = int(datos.get('version') or 1)
    except (TypeError, ValueError):
        raise ErrorServicio('La versión debe ser un número.')
    if not 1 <= version <= 999:
        raise ErrorServicio('La versión va de 1 a 999.')
    fecha = None
    if datos.get('fecha'):
        try:
            fecha = date.fromisoformat(str(datos['fecha'])[:10])
        except ValueError:
            raise ErrorServicio('La fecha de la ficha no es válida.')
    equipo = st.obtener_equipo(equipo_id)
    if not equipo:
        raise ErrorServicio('El equipo no existe.')
    # Cada fila llega con su etiqueta (etiqueta_N, fila_N, destacar_N); solo se
    # aceptan las de la ficha de este equipo.
    permitidas = {etq for etq, _v in filas_base(equipo)} | set((equipo.get('ficha') or {}).get('filas', {}))
    filas, destacar = {}, []
    for i in range(80):
        etq = datos.get(f'etiqueta_{i}')
        if etq is None:
            break
        if etq not in permitidas:
            continue
        valor = ' '.join(str(datos.get(f'fila_{i}') or '').split())[:600]
        if valor:
            filas[etq] = valor
        if datos.get(f'destacar_{i}'):
            destacar.append(etq)
    recomendaciones = [' '.join(r.split())[:300] for r in str(datos.get('recomendaciones') or '').split('\n')
                       if r.strip()][:12]
    fotos = []
    validas = {f['id'] for f in st.fotos_de_equipo(equipo_id)}
    for valor in datos.get('fotos') or []:
        if str(valor).isdigit() and int(valor) in validas and int(valor) not in fotos:
            fotos.append(int(valor))
    descripcion = str(datos.get('descripcion') or '').strip()[:1500] or None
    ficha = {
        'estado': estado, 'version': version, 'fecha': fecha.isoformat() if fecha else None,
        'descripcion': descripcion,
        'asignado_a': _texto(datos.get('asignado_a'), 150), 'empresa': _texto(datos.get('empresa'), 150),
        'filas': filas, 'destacar': destacar,
        'vida_util': (str(datos.get('vida_util') or '').strip()[:2500] or None),
        'recomendaciones': recomendaciones,
        'fabricante': _texto(datos.get('fabricante'), 150), 'fabricante_detalle': _texto(datos.get('fabricante_detalle'), 250),
        'problema': (str(datos.get('problema') or '').strip()[:1500] or None),
        'requerimientos': (str(datos.get('requerimientos') or '').strip()[:2500] or None),
        'fotos': fotos[:FOTOS_EN_FICHA],
    }
    ficha = {k: v for k, v in ficha.items() if v not in (None, '', [], {})}
    with get_db_cursor() as cur:
        # La descripción de la ficha es también el resumen del equipo (se ve en su página).
        cur.execute("""UPDATE st_equipos SET ficha = %s::jsonb, resumen_ia = COALESCE(%s, resumen_ia),
                              actualizado_en = NOW()
                       WHERE id = %s""", (json.dumps(ficha, ensure_ascii=False), descripcion, equipo_id))
        st._evento(cur, None, equipo_id, 'equipo',
                   'Ficha técnica actualizada (' + ('presenta inconvenientes' if estado == 'inconveniente'
                                                   else 'en buen estado') + ')', usuario_id)
    return ficha


def guardar_copia(equipo_id, nombre, contenido, codigo=None, usuario_id=None):
    """Guarda el PDF generado en los documentos del equipo (historial de fichas)."""
    with get_db_cursor() as cur:
        doc_id = st.guardar_documento(cur, nombre, 'application/pdf', contenido, equipo_id=equipo_id,
                                      usuario_id=usuario_id, descripcion=f'Ficha técnica {codigo or ""}'.strip())
        st._evento(cur, None, equipo_id, 'documento', f'Copia de la ficha técnica {codigo or ""} guardada'.replace('  ', ' '),
                   usuario_id)
    return doc_id


def prefijo_configurado():
    from services.servicio_tecnico_mensajes import config
    try:
        return (config().get('ficha_prefijo') or '').strip()
    except Exception:  # noqa: BLE001
        return ''


def siguiente_codigo(codigos, prefijo=''):
    """Siguiente consecutivo: sigue la serie del prefijo configurado o, si no
    hay, la que más se usa (CYBER-F00-CS-014 → CYBER-F00-CS-015)."""
    series = {}
    for c in codigos:
        m = re.fullmatch(r'(.*?)(\d+)', (c or '').strip())
        if m:
            pref, num = m.group(1), m.group(2)
            maximo, digitos, veces = series.get(pref.upper(), (0, 3, 0))
            series[pref.upper()] = (max(maximo, int(num)), max(digitos, len(num)), veces + 1)
    if prefijo:
        maximo, digitos, _v = series.get(prefijo.upper(), (0, 3, 0))
        return f'{prefijo}{maximo + 1:0{digitos}d}'
    if series:
        pref = max(series, key=lambda k: (series[k][2], series[k][0]))
        maximo, digitos, _v = series[pref]
        return f'{pref}{maximo + 1:0{digitos}d}'
    return 'FT-001'


def asignar_codigo(equipo_id):
    """El consecutivo de la ficha (se asigna la primera vez que se genera)."""
    with get_db_cursor() as cur:
        cur.execute('SELECT ficha_codigo FROM st_equipos WHERE id = %s FOR UPDATE', (equipo_id,))
        fila = cur.fetchone()
        if not fila:
            raise ErrorServicio('El equipo no existe.')
        if fila[0]:
            return fila[0]
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('st_ficha_codigo'))")
        cur.execute('SELECT ficha_codigo FROM st_equipos WHERE ficha_codigo IS NOT NULL')
        codigo = siguiente_codigo([r[0] for r in cur.fetchall()], prefijo_configurado())
        cur.execute('UPDATE st_equipos SET ficha_codigo = %s WHERE id = %s', (codigo, equipo_id))
        st._evento(cur, None, equipo_id, 'equipo', f'Ficha técnica {codigo} generada', None)
    return codigo


# ── Borrador con reglas (sin IA) ────────────────────────────────
def _numero_gb(texto):
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*GB', str(texto or ''), re.I)
    return float(m.group(1).replace(',', '.')) if m else None


def _gama(procesador):
    t = _norm(procesador)
    if re.search(r'\bi[79]\b|i[79] \d|ryzen [79]|ultra [79]|\bm[1-4] (pro|max)|xeon', t):
        return 'media-alta', ('ofimática, videoconferencias, multitarea y tareas de productividad exigentes'), '5 a 7'
    if re.search(r'\bi5\b|i5 \d|ryzen 5|ultra 5|apple m\d|\bm[1-4]\b', t):
        return 'media', ('ofimática, navegación en internet, videoconferencias, multimedia y aplicaciones de '
                         'productividad de exigencia media'), '5 a 7'
    return 'básica', 'ofimática, navegación en internet, videoconferencias y tareas de productividad ligera', '4 a 6'


def _procesador_corto(procesador):
    t = re.sub(r'\s+with\s+Radeon.*$|\s*@.*$|,.*$|\(R\)|\(TM\)|CPU', '', str(procesador or ''), flags=re.I)
    return ' '.join(t.split())


def borrador(equipo):
    """Textos de la ficha con reglas fijas, al estilo de las fichas del taller."""
    tipo = equipo.get('tipo')
    extras = equipo.get('extras') or {}
    nombre = ' '.join(x for x in ((equipo.get('marca') if not _norm(equipo.get('modelo') or '').startswith(
        _norm(equipo.get('marca') or '-')) else None), equipo.get('modelo')) if x)
    articulo = {'portatil': 'un portátil', 'computador': 'un computador de escritorio', 'celular': 'un celular',
                'tablet': 'una tablet', 'televisor': 'un televisor', 'monitor': 'un monitor',
                'impresora': 'una impresora', 'ups': 'una UPS', 'consola': 'una consola'}.get(tipo, 'un equipo')
    es_pc = tipo in ('computador', 'portatil')
    proc = _procesador_corto(equipo.get('procesador'))
    ram_gb = _numero_gb(equipo.get('ram'))
    # «8 GB de RAM», como en las fichas del taller (sin «DDR4» ni ranuras).
    ram = (f'{ram_gb:g}'.replace('.', ',') + ' GB') if ram_gb else (equipo.get('ram') or '')
    gama, usos, anios = _gama(equipo.get('procesador'))
    partes = []
    if proc:
        partes.append(f'procesador {proc}')
    if ram:
        partes.append(f'{ram} de RAM')
    if equipo.get('almacenamiento'):
        partes.append(f"almacenamiento {equipo['almacenamiento']}")
    sujeto = 'Este equipo de cómputo es' if es_pc else 'Este equipo es'
    descripcion = f"{sujeto} {articulo}{(' ' + nombre) if nombre else ''}"
    if partes:
        descripcion += ' con ' + ', '.join(partes[:-1]) + (' y ' if len(partes) > 1 else '') + partes[-1]
    descripcion += '.'
    if es_pc:
        descripcion += f' Es un equipo de gama {gama} apto para {usos}.'

    problemas, requerimientos, destacar, recomendaciones = [], [], [], []
    libres = extras.get('ram_ranuras_libres')
    if es_pc and ram_gb and ram_gb < 16:
        problemas.append(f'Memoria RAM insuficiente: {ram} instalados, lo que limita el rendimiento.')
        if libres not in (None, '') and str(libres) != '0':
            requerimientos.append('Ampliación de memoria RAM a 16 GB (mínimo recomendado) aprovechando la ranura libre.')
        elif str(libres) == '0':
            requerimientos.append('Ampliación de memoria RAM a 16 GB (mínimo recomendado): no hay ranuras libres, '
                                  'se deben reemplazar los módulos actuales.')
        else:
            requerimientos.append('Ampliación de memoria RAM a 16 GB (mínimo recomendado).')
        destacar += ['Memoria RAM', 'Memoria física disponible']
    disco = (extras.get('tipo_disco') or equipo.get('almacenamiento') or '').upper()
    if es_pc and 'HDD' in disco and 'SSD' not in disco:
        problemas.append('Disco duro mecánico (HDD): es la causa más común de lentitud.')
        requerimientos.append('Cambio del disco duro por una unidad SSD.')
        destacar.append('Unidad de Disco')
    desgaste = extras.get('bateria_desgaste')
    salud = extras.get('bateria_salud')
    try:
        if (desgaste and float(str(desgaste).replace(',', '.')) >= 30) or (salud and float(str(salud).replace(',', '.')) <= 80):
            problemas.append('Batería con desgaste alto.')
            requerimientos.append('Cambio de batería.')
    except ValueError:
        pass
    so = _norm(equipo.get('sistema_operativo'))
    if re.search(r'windows (7|8|10)\b', so):
        problemas.append('Sistema operativo sin soporte de seguridad.')
        requerimientos.append('Actualización a Windows 11 (si el equipo es compatible).')
        destacar.append('Sistema Operativo')
    if es_pc:
        requerimientos.append('Incluye mantenimiento preventivo: limpieza interna y cambio de pasta térmica.'
                              if problemas else 'Mantenimiento preventivo: limpieza interna, cambio de pasta térmica '
                                                'y verificación de la unidad de almacenamiento.')
        recomendaciones = ['Conectarlo a un regulador de voltaje o UPS.',
                           'Realizar mantenimiento periódico al sistema de enfriamiento y cambio de pasta térmica.']
        if ram_gb and ram_gb < 16:
            recomendaciones.append('Ampliar la memoria RAM para mejorar el rendimiento.')
        if tipo == 'portatil':
            recomendaciones.append('Cuidar el ciclo de carga de la batería y evitar descargas totales.')
        if 'windows' in so:
            version = re.search(r'windows (\d+)', so)
            recomendaciones.append('Desinstalar programas innecesarios y mantener Windows '
                                   f'{version.group(1) if version else ""} actualizado.'.replace('  ', ' '))
        recomendaciones.append('Mantenerlo limpio y libre de polvo (teclado, rejillas y ventilador).')
        entre = ', '.join(x for x in (proc, f'{ram} de RAM' if ram else None) if x)
        vida = (f'La vida útil estimada de {articulo} como este{f" ({entre})" if entre else ""}'
                f' es de {anios} años desde su fabricación, dependiendo del uso, el mantenimiento y las '
                'actualizaciones realizadas.')
        if es_pc and ram_gb and ram_gb < 16:
            vida += f' Actualmente la memoria RAM ({ram}) limita el rendimiento; se recomienda ampliarla.'
        elif 'Unidad de Disco' in destacar:
            vida += ' Actualmente el disco mecánico (HDD) lo hace lento; se recomienda cambiarlo por una unidad SSD.'
        elif problemas:
            vida += ' ' + problemas[0].rstrip('.') + '; se recomienda atenderlo.'
        vida += ' Recomendaciones:'
    else:
        vida = ('La vida útil depende del uso y del mantenimiento. Recomendaciones:')
        recomendaciones = ['Conectarlo a un regulador de voltaje o UPS.' if tipo not in ('celular', 'tablet') else
                           'Usar el cargador original y evitar descargas totales de la batería.',
                           'Mantenerlo limpio y libre de polvo.']
        requerimientos.append('Mantenimiento preventivo.' if not problemas else '')
    return {
        'estado': 'inconveniente' if problemas else 'bueno',
        'descripcion': descripcion,
        'vida_util': vida,
        'recomendaciones': recomendaciones,
        'problema': ' '.join(problemas) if problemas else 'N/A - El equipo no presenta fallas.',
        'requerimientos': ' '.join(r for r in requerimientos if r),
        'destacar': [d for d in dict.fromkeys(destacar)],
    }


# ── Reconocer la ficha en un PDF (importador) ───────────────────
_ETIQUETAS = {_norm(e): e for e in FILAS_PC}
_ETIQUETAS.update({'memoria fisica disponible': 'Memoria física disponible', 'fabricante': 'Fabricante del Sistema',
                   'directorio del sistema': 'Directorios del Sistema', 'unidad de disco duro': 'Unidad de Disco'})
_VINETAS = '✅☑✔✓•▪●'


def es_ficha(texto):
    t = _norm(texto)
    return 'ficha tecnica' in t and 'caracteristicas globales' in t and (
        'equipo asignado a' in t or 'descripcion del problema' in t)


def _colores(pagina):
    """Cuántos rellenos rojos tiene la hoja y qué textos van en rojo."""
    estado = {'color': None}
    textos_rojos, rellenos = [], 0
    try:
        contenido = pagina.get_contents().get_data().decode('latin-1')
        rellenos = len(re.findall(r'(?<![\d.])1 0?\.3\d* 0?\.3\d* rg', contenido))
    except Exception:  # noqa: BLE001
        pass

    def antes(op, args, cm, tm):
        try:
            if op in (b'rg', b'sc', b'scn') and len(args) == 3:
                estado['color'] = tuple(float(a) for a in args)
            elif op in (b'g', b'sc', b'scn') and len(args) == 1:
                estado['color'] = (float(args[0]),) * 3
            elif op == b'k' and len(args) == 4:
                estado['color'] = None
        except (TypeError, ValueError):
            estado['color'] = None

    def texto(t, cm, tm, fd, fs):
        c = estado['color']
        if t.strip() and c and c[0] > 0.7 and c[1] < 0.45 and c[2] < 0.45:
            textos_rojos.append(' '.join(t.split()))
    try:
        pagina.extract_text(visitor_operand_before=antes, visitor_text=texto)
    except Exception:  # noqa: BLE001
        pass
    return {'rellenos_rojos': rellenos, 'textos_rojos': textos_rojos}


def fotos_de_pdf(datos, maximo=4):
    """Las fotos del equipo que trae el PDF (JPEG); el logo (PNG) no."""
    from pypdf import PdfReader
    salida = []
    try:
        for pagina in PdfReader(io.BytesIO(datos)).pages[:2]:
            for imagen in pagina.images:
                nombre = (imagen.name or '').lower()
                if nombre.endswith('.png') or len(imagen.data) < 1500:
                    continue
                salida.append(imagen.data)
                if len(salida) >= maximo:
                    return salida
    except Exception:  # noqa: BLE001
        return salida
    return salida


def leer_pdf(datos):
    """La ficha técnica de un PDF con este formato, o None si no lo es."""
    from pypdf import PdfReader
    try:
        lector = PdfReader(io.BytesIO(datos))
        if lector.is_encrypted and not lector.decrypt(''):
            return None
        pagina = lector.pages[0]
        texto = pagina.extract_text(extraction_mode='layout') or ''
    except Exception:  # noqa: BLE001
        return None
    if not es_ficha(texto):
        return None
    try:
        ficha = leer_texto(texto, **_colores(pagina))
    except Exception:  # noqa: BLE001
        return None                                  # una ficha con forma rara se lee como texto común
    ficha['fotos'] = len(fotos_de_pdf(datos))
    return ficha


def _partir(linea):
    return [x for x in re.split(r'\s{3,}', linea.strip()) if x]


def _unir_lineas(lineas):
    salida = ''
    for linea in lineas:
        linea = ' '.join(linea.split())
        if not linea:
            continue
        if salida.endswith('-') and len(salida) > 1 and salida[-2].isalnum() and linea[:1].isalnum():
            salida += linea                        # «15-» + «gw0»: palabra partida al final de la línea
        else:
            salida = (salida + ' ' + linea).strip()
    return salida


def _fila_sin_etiqueta(texto, ya):
    if 'BIOS' not in ya and re.search(r'SMBIOS|\bUEFI\b|\bBIOS\b', texto):
        return 'BIOS'
    if 'Directorios del Sistema' not in ya and re.search(r'[A-Z]:\\', texto):
        return 'Directorios del Sistema'
    if 'Memoria virtual' not in ya and re.search(r'paginaci|memoria virtual', texto, re.I):
        return 'Memoria virtual'
    return None


def leer_texto(texto, rellenos_rojos=0, textos_rojos=()):
    """Lee el texto (modo «layout» de pypdf) de una ficha técnica."""
    lineas = [l.rstrip() for l in texto.replace('\r', '').split('\n')]
    planos = [_norm(l) for l in lineas]

    def buscar(condicion, desde=0):
        return next((i for i in range(desde, len(lineas)) if condicion(planos[i])), None)
    f = {'formato': 'ficha_tecnica'}
    plano_todo = '\n'.join(lineas)
    m = re.search(r'CODIGO\s+(\S+)', plano_todo)
    codigo = m.group(1) if m else None
    if codigo and codigo.endswith('-'):              # código largo partido en dos líneas
        siguiente = plano_todo[m.end():].split('\n', 2)[1:2]
        resto = re.search(r'([A-Z0-9][\w-]*)\s*$', siguiente[0]) if siguiente else None
        if resto:
            codigo += resto.group(1)
    f['codigo'] = codigo[:40] if codigo else None
    m = re.search(r'\bFECHA\s+(?!PROXIMO)(\d{1,4}[-/][\w]{1,4}[-/]\d{2,4})', plano_todo)
    f['fecha'] = leer_fecha(m.group(1)).isoformat() if m and leer_fecha(m.group(1)) else None
    m = re.search(r'FECHA PROXIMO\s+(\d{1,4}[-/][\w]{1,4}[-/]\d{2,4})', plano_todo)
    f['proximo'] = leer_fecha(m.group(1)).isoformat() if m and leer_fecha(m.group(1)) else None
    m = re.search(r'VERSION\s+(\d{1,3})', plano_todo)
    f['version'] = int(m.group(1)) if m else 1
    m = re.search(r'EQUIPO ASIGNADO A\s+(.+)', plano_todo)
    titulo = ' '.join(m.group(1).split()) if m else ''
    if ' - ' in titulo:
        f['asignado_a'], f['empresa'] = [x.strip() for x in titulo.rsplit(' - ', 1)]
    else:
        f['asignado_a'], f['empresa'] = titulo or None, None

    i_car = buscar(lambda t: 'caracteristicas globales' in t)
    i_desc = buscar(lambda t: t.startswith('descripcion') and 'problema' not in t)
    i_vida = buscar(lambda t: t == 'vida util' or t.startswith('vida util'), (i_car or 0))
    i_fab = buscar(lambda t: t.startswith('datos del fabricante'), (i_vida or 0))
    i_prob = buscar(lambda t: t.startswith('descripcion del problema'), (i_fab or 0))
    i_req = buscar(lambda t: t.startswith('detalle tecnico'), (i_prob or i_fab or 0))

    if i_desc is not None and i_car is not None:
        cuerpo = [re.sub(r'\s*\b(?:GENERAL DEL|DESCRIPCI[OÓ]N|DEL EQUIPO)\b\s*', ' ', l) for l in lineas[i_desc + 1:i_car]]
        f['descripcion'] = _unir_lineas(cuerpo)
    filas, actual = [], None
    for linea in lineas[(i_car or 0) + 1:(i_vida or len(lineas))]:
        partes = _partir(linea)
        if not partes:
            continue
        sangria = len(linea) - len(linea.lstrip())
        etiqueta = _ETIQUETAS.get(_norm(partes[0])) if sangria < 45 else None
        if etiqueta:
            actual = [etiqueta, ' '.join(partes[1:])]
            filas.append(actual)
            continue
        resto = ' '.join(partes)
        nueva = _fila_sin_etiqueta(resto, {x[0] for x in filas})
        if nueva:
            actual = [nueva, resto]
            filas.append(actual)
        elif actual:
            actual[1] = _unir_lineas([actual[1], resto])
    f['filas'] = [(e, ' '.join(v.split())) for e, v in filas if v.strip()]
    if i_vida is not None:
        lineas_vida = lineas[i_vida + 1:(i_fab or len(lineas))]
        bloque = _unir_lineas(lineas_vida)
        partes = re.split('[' + _VINETAS + ']', bloque)
        f['vida_util'] = partes[0].strip()
        f['recomendaciones'] = [' '.join(x.split()) for x in partes[1:] if x.strip()][:12]
        marca = next((k for k, l in enumerate(lineas_vida) if re.search(r'(?i)recomendaciones\s*:\s*$', l.strip())), None)
        if not f['recomendaciones'] and marca is not None:
            # Sin viñetas de texto (casillas dibujadas): cada recomendación empieza con mayúscula.
            f['vida_util'] = _unir_lineas(lineas_vida[:marca + 1])
            items = []
            for linea in lineas_vida[marca + 1:]:
                texto = ' '.join(linea.split())
                if not texto:
                    continue
                if texto[:1].isupper() or not items:
                    items.append(texto)
                else:
                    items[-1] = _unir_lineas([items[-1], texto])
            f['recomendaciones'] = items[:12]
    if i_fab is not None:
        cab = _partir(lineas[i_fab])
        f['fabricante'] = ' '.join(cab[1:]) if len(cab) > 1 else None
        f['fabricante_detalle'] = _unir_lineas(lineas[i_fab + 1:(i_prob or i_req or len(lineas))]) or None
    if i_prob is not None:
        cab = _partir(lineas[i_prob])
        f['problema'] = _unir_lineas([' '.join(cab[1:])] + lineas[i_prob + 1:(i_req or len(lineas))]) or None
    if i_req is not None:
        cuerpo = [re.sub(r'^\s*(?:DETALLE TECNICO DE|DETALLE TECNICO|REQUERIMIENTOS)\b', '', l) for l in lineas[i_req:]]
        f['requerimientos'] = _unir_lineas(cuerpo) or None
    rojos = {_norm(t) for t in textos_rojos}
    f['destacar'] = [e for e, _v in f['filas'] if _norm(e) in rojos]
    problema = _norm(f.get('problema'))
    f['estado'] = 'inconveniente' if rellenos_rojos >= 3 or (problema and not problema.startswith('n a')) else 'bueno'
    return f
