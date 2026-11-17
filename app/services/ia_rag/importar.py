"""Leer el texto de un PDF, Word (.docx) o texto plano para un documento interno.

El dueño sube su manual o su política y el texto queda en el formulario de
/admin/ia/documentos para revisarlo antes de guardar: nada se guarda solo.

- PDF: pypdf (ya está en requirements.txt). Un PDF escaneado (sin texto) no se
  puede leer así: se avisa.
- Word: un .docx es un ZIP con XML; se lee con la librería estándar (sin
  dependencias nuevas). El .doc viejo no: se pide guardarlo como .docx o PDF.
- Texto: .txt / .md en UTF-8 (o Latin-1 si no).

Límites para no tumbar el servidor con un archivo raro: 10 MB, 300 páginas y
40 MB descomprimidos en un Word.
"""
import io
import os
import re
import zipfile
from xml.etree import ElementTree

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGINAS = 300
MAX_DESCOMPRIMIDO = 40 * 1024 * 1024
EXTENSIONES = ('.pdf', '.docx', '.txt', '.md')
_W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def _limpiar(texto):
    """Espacios ordenados y párrafos separados por una línea en blanco (así el
    indexador parte el documento por párrafos)."""
    lineas = [re.sub(r'[ \t ]+', ' ', l).strip() for l in str(texto or '').splitlines()]
    texto = '\n'.join(lineas)
    texto = re.sub(r'\n{3,}', '\n\n', texto)
    return texto.strip()


def _pdf(datos):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    try:
        lector = PdfReader(io.BytesIO(datos))
        if lector.is_encrypted:
            try:
                lector.decrypt('')
            except Exception:  # noqa: BLE001
                raise ValueError('El PDF tiene contraseña. Quítasela y vuelve a subirlo.')
        paginas = lector.pages
        if len(paginas) > MAX_PAGINAS:
            raise ValueError(f'El PDF tiene {len(paginas)} páginas; el máximo es {MAX_PAGINAS}. '
                             'Divídelo en partes.')
        texto = '\n\n'.join((p.extract_text() or '') for p in paginas)
    except PdfReadError:
        raise ValueError('No se pudo leer el PDF: parece dañado.')
    if len(_limpiar(texto)) < 20:
        raise ValueError('El PDF no tiene texto para leer (parece escaneado o son imágenes). '
                         'Súbelo como Word o pega el texto.')
    return texto


def _docx(datos):
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            try:
                info = z.getinfo('word/document.xml')
            except KeyError:
                raise ValueError('Ese archivo no es un Word (.docx) válido.')
            if info.file_size > MAX_DESCOMPRIMIDO:
                raise ValueError('El Word es demasiado grande para leerlo.')
            xml = z.read(info)
    except zipfile.BadZipFile:
        raise ValueError('Ese archivo no es un Word (.docx) válido. Si es un .doc antiguo, '
                         'guárdalo como .docx o PDF.')
    try:
        raiz = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        raise ValueError('No se pudo leer el Word: parece dañado.')
    parrafos = []
    for p in raiz.iter(f'{_W}p'):
        partes = []
        for el in p.iter():
            if el.tag == f'{_W}t' and el.text:
                partes.append(el.text)
            elif el.tag == f'{_W}tab':
                partes.append('\t')
            elif el.tag in (f'{_W}br', f'{_W}cr'):
                partes.append('\n')
        parrafos.append(''.join(partes))
    return '\n\n'.join(parrafos)


def _plano(datos):
    try:
        return datos.decode('utf-8-sig')
    except UnicodeDecodeError:
        return datos.decode('latin-1')


def texto_de_archivo(nombre, datos):
    """(titulo_sugerido, texto). ValueError con un mensaje para el dueño."""
    nombre = os.path.basename(str(nombre or '')).strip()
    extension = os.path.splitext(nombre.lower())[1]
    if extension not in EXTENSIONES:
        raise ValueError('Sube un PDF, un Word (.docx) o un texto (.txt).')
    if not datos:
        raise ValueError('El archivo está vacío.')
    if len(datos) > MAX_BYTES:
        raise ValueError('El archivo pesa más de 10 MB. Divídelo en partes.')
    if extension == '.pdf':
        texto = _pdf(datos)
    elif extension == '.docx':
        texto = _docx(datos)
    else:
        texto = _plano(datos)
    texto = _limpiar(texto)
    if not texto:
        raise ValueError('El archivo no tiene texto.')
    titulo = re.sub(r'[_\-]+', ' ', os.path.splitext(nombre)[0]).strip()[:200] or 'Documento'
    return titulo, texto
