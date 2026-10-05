"""Servicio Técnico: lector fijo de la «información del sistema» pegada.

Funciona SIN IA. Reconoce lo más común:
  - Windows: `systeminfo` (español e inglés), msinfo32, CPU-Z, `wmic memorychip`,
    reporte de batería de `powercfg /batteryreport`.
  - Android / iPhone: pantallas «Acerca del teléfono» / «Información».
  - Etiquetas de UPS y baterías (VA, W, V, Ah).
La IA (servicio_tecnico_ia) completa lo que este lector no entiende; lo que
este lector sí saca tiene prioridad (serial e IMEI no se inventan).

`limpiar_personales` quita del texto lo que identifica a una persona (usuario
de Windows, nombre del equipo, dominio, correos, teléfonos, claves de producto)
antes de guardarlo o mandarlo a la IA.
"""

import re

_LINEAS_PERSONALES = re.compile(
    r'(propietario registrado|registered owner|organizaci[oó]n registrada|registered organization|'
    r'nombre de host|host ?name|nombre del equipo|computer name|nombre de usuario|user ?name|usuario|'
    r'dominio|domain|servidor de inicio de sesi[oó]n|logon server|id\. del producto|product id|'
    r'clave de producto|product key|direcci[oó]n(es)? ip|ip address|mac|direcci[oó]n f[ií]sica|'
    r'cuenta|account|correo|e-?mail|tel[eé]fono|phone number|n[uú]mero de tel[eé]fono)\s*[:=\t]',
    re.I)
_CORREO = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
_TELEFONO = re.compile(r'(?<!\d)(?:\+?57\s?)?3\d{2}[\s-]?\d{3}[\s-]?\d{4}(?!\d)')
MAX_TEXTO = 12000


def limpiar_personales(texto):
    """Texto sin líneas ni datos que identifiquen a una persona."""
    texto = (texto or '')[:MAX_TEXTO * 2]
    lineas = []
    for linea in texto.replace('\r', '').split('\n'):
        if _LINEAS_PERSONALES.search(linea):
            continue
        linea = _CORREO.sub('[correo]', linea)
        linea = _TELEFONO.sub('[teléfono]', linea)
        lineas.append(linea.rstrip())
    limpio = '\n'.join(lineas)
    limpio = re.sub(r'\n{3,}', '\n\n', limpio).strip()
    return limpio[:MAX_TEXTO]


def _valor(texto, *etiquetas):
    """Valor de la primera «Etiqueta: valor» (o con tabulador) que aparezca."""
    for etq in etiquetas:
        m = re.search(r'^[ \t]*' + etq + r'[ \t]*(?::|\t| {2,})[ \t]*(.+?)[ \t]*$', texto, re.I | re.M)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


def _gb(texto_num):
    """«8.192 MB» / «16,0 GB» / «16 GB» → «8 GB» / «16 GB»."""
    m = re.search(r'([\d.,]+)\s*(MB|GB|TB)', texto_num or '', re.I)
    if not m:
        return None
    numero = m.group(1)
    if re.fullmatch(r'\d{1,3}([.,]\d{3})+', numero):      # 8.192 / 16,384
        numero = re.sub(r'[.,]', '', numero)
    else:
        numero = numero.replace(',', '.')
    try:
        n = float(numero)
    except ValueError:
        return None
    unidad = m.group(2).upper()
    if unidad == 'MB':
        n = n / 1024
    elif unidad == 'TB':
        n = n * 1024
    # La RAM física siempre reporta un poco menos (7,8 GB → 8 GB).
    for redondo in (2, 3, 4, 6, 8, 12, 16, 20, 24, 32, 48, 64, 96, 128, 256, 512, 1024, 2048):
        if abs(n - redondo) / redondo < 0.06:
            n = redondo
            break
    return f'{n:.0f} GB' if n >= 1 else f'{n * 1024:.0f} MB'


def imei_luhn(imei):
    d = re.sub(r'\D', '', imei or '')
    if len(d) != 15:
        return False
    total = 0
    for i, ch in enumerate(d):
        n = int(ch)
        if i % 2:
            n *= 2
            n -= 9 if n > 9 else 0
        total += n
    return total % 10 == 0


def leer(texto, tipo=None):
    """{'columnas': {...}, 'extras': {...}} con lo que se reconoce del texto."""
    t = (texto or '').replace('\r', '')
    col, ext = {}, {}

    # Sistema operativo
    so = _valor(t, r'Nombre del sistema operativo', r'OS Name', r'Nombre del SO', r'Sistema operativo')
    version = _valor(t, r'Versi[oó]n del sistema operativo', r'OS Version', r'Versi[oó]n de Android',
                     r'Android version', r'Versi[oó]n de software', r'Versi[oó]n de iOS', r'Software Version')
    if so:
        col['sistema_operativo'] = so.replace('Microsoft ', '')[:120]
    elif re.search(r'Versi[oó]n de Android|Android version', t, re.I) and version:
        col['sistema_operativo'] = f'Android {version}'[:120]
    elif re.search(r'iOS', t) and version:
        col['sistema_operativo'] = f'iOS {version}'[:120]
    if version and tipo in ('celular', 'tablet'):
        ext['version_sistema'] = version[:60]

    # Marca y modelo
    marca = _valor(t, r'Fabricante del sistema', r'System Manufacturer', r'Fabricante', r'Manufacturer', r'Marca')
    modelo = _valor(t, r'Modelo del sistema', r'Modelo el sistema', r'System Model', r'Nombre del modelo',
                    r'Model name', r'Modelo', r'Model')
    if marca and not re.search(r'to be filled|default string|system manufacturer', marca, re.I):
        col['marca'] = marca[:80]
    if modelo and not re.search(r'to be filled|default string|system product', modelo, re.I):
        col['modelo'] = modelo[:120]

    # Serial / IMEI
    serial = _valor(t, r'N[uú]mero de serie', r'Serial Number', r'Serial No\.?', r'S/N', r'Serie', r'Serial')
    if serial and re.fullmatch(r'[\w\-./]{4,40}', serial):
        col['serial'] = serial[:120]
    # IMEI: en la línea que dice «IMEI» (también «IMEI (ranura 1)»), el número de 15 dígitos.
    imeis = []
    for linea in t.split('\n'):
        if 'imei' in linea.lower():
            for crudo in re.findall(r'(?<!\d)\d[\d ]{13,18}\d(?!\d)', linea):
                numero = re.sub(r'\D', '', crudo)
                if imei_luhn(numero) and numero not in imeis:
                    imeis.append(numero)
    if imeis:
        col['imei'] = imeis[0]
        if len(imeis) > 1 and imeis[1] != imeis[0]:
            ext['imei2'] = imeis[1]

    # Procesador
    cpu = re.search(r'((?:Intel\(R\)\s*)?(?:Core\(TM\)\s*)?(?:Intel\s+)?(?:Core\s+)?(?:i[3579]|Ultra\s\d)[- ]\s?\d{3,5}\w*'
                    r'|AMD\s+Ryzen\s+\d\s+\d{3,5}\w*|Apple\s+M\d\w*(?:\s+(?:Pro|Max|Ultra))?|Snapdragon\s+[\w+ ]{2,20}'
                    r'|Exynos\s+\d{3,4}|MediaTek\s+[\w ]{3,20}|Celeron\s+\w+|Pentium\s+\w+|Athlon\s+\w+)', t, re.I)
    proc = _valor(t, r'Procesador', r'Processor')
    if cpu:
        col['procesador'] = re.sub(r'\((?:R|TM)\)', '', cpu.group(1)).replace('  ', ' ').strip()[:160]
    elif proc and not re.search(r'Family \d+ Model', proc, re.I):
        col['procesador'] = proc[:160]

    # RAM
    ram = _valor(t, r'Memoria f[ií]sica total', r'Total Physical Memory', r'Memoria f[ií]sica instalada \(RAM\)',
                 r'Installed Physical Memory \(RAM\)', r'Memoria RAM', r'RAM', r'Memoria')
    ram_gb = _gb(ram) if ram else None
    if ram_gb:
        tipo_ram = re.search(r'\b(LP)?DDR\d\w?\b', t)
        col['ram'] = f'{ram_gb} {tipo_ram.group(0)}' if tipo_ram else ram_gb

    # Ranuras de RAM (CPU-Z «Slots», wmic memorychip, «Ranuras de memoria»)
    total = re.search(r'(?:Ranuras(?: de memoria)?|Memory slots|Slots totales|Total slots)\s*[:\t ]\s*(\d)', t, re.I)
    usadas = re.search(r'(?:Ranuras usadas|Used slots|Slots usados)\s*[:\t ]\s*(\d)', t, re.I)
    if total:
        ext['ram_ranuras_total'] = total.group(1)
        if usadas:
            ext['ram_ranuras_libres'] = str(max(0, int(total.group(1)) - int(usadas.group(1))))
    libres = re.search(r'(\d)\s*(?:libre|free)', t, re.I)
    if libres and 'ram_ranuras_libres' not in ext:
        ext['ram_ranuras_libres'] = libres.group(1)

    # Almacenamiento
    disco = re.search(r'(\d{2,4}\s*(?:GB|TB))\s*(?:\w+\s){0,3}?(NVMe|SSD|HDD|eMMC)|(NVMe|SSD|HDD|eMMC)\s*(?:\w+\s){0,3}?(\d{2,4}\s*(?:GB|TB))', t, re.I)
    almac = _valor(t, r'Almacenamiento interno', r'Almacenamiento', r'Storage', r'Capacidad')
    if disco:
        cap = disco.group(1) or disco.group(4)
        clase = (disco.group(2) or disco.group(3)).upper().replace('NVME', 'NVMe').replace('EMMC', 'eMMC')
        col['almacenamiento'] = f'{clase} {cap.replace(" ", " ")}'
        ext['tipo_disco'] = {'NVMe': 'SSD NVMe', 'SSD': 'SSD SATA', 'HDD': 'HDD', 'eMMC': 'eMMC'}[clase]
    elif almac:
        cap = re.search(r'\d{2,4}\s*(?:GB|TB)', almac, re.I)
        if cap:
            col['almacenamiento'] = cap.group(0)

    # Pantalla
    pulg = re.search(r'(\d{1,2}(?:[.,]\d)?)\s*(?:"|”|pulgadas|inch|in\b)', t, re.I)
    if pulg:
        if tipo in ('televisor', 'monitor'):
            ext['pulgadas'] = pulg.group(1).replace(',', '.')
        else:
            col['pantalla'] = pulg.group(1).replace('.', ',') + '"'

    # Batería: salud (celular) o desgaste (portátil, powercfg)
    salud = re.search(r'(?:Salud de la bater[ií]a|Battery health|Capacidad m[aá]xima|Maximum capacity)\s*[:\t ]\s*(\d{2,3})\s*%', t, re.I)
    if salud:
        ext['bateria_salud'] = salud.group(1)
    dis = re.search(r'DESIGN CAPACITY\s+([\d.,]+)\s*mWh', t, re.I)
    full = re.search(r'FULL CHARGE CAPACITY\s+([\d.,]+)\s*mWh', t, re.I)
    if dis and full:
        a = float(re.sub(r'[.,]', '', dis.group(1)))
        b = float(re.sub(r'[.,]', '', full.group(1)))
        if a > 0 and 0 <= b <= a * 1.1:
            ext['bateria_desgaste'] = str(max(0, round((1 - b / a) * 100)))

    # UPS / baterías
    if tipo in ('ups', 'bateria') or re.search(r'\bUPS\b|\bVA\b', t):
        va = re.search(r'(\d{3,5})\s*VA\b', t, re.I)
        w = re.search(r'(\d{3,5})\s*W(?:atts?)?\b', t, re.I)
        bat = re.search(r'(\d{1,2})\s*V\s*(\d{1,3}(?:[.,]\d)?)\s*Ah', t, re.I)
        if va:
            ext['capacidad_va'] = va.group(1)
        if w:
            ext['capacidad_w'] = w.group(1)
        if bat:
            clave = 'baterias_voltaje' if tipo == 'ups' else 'voltaje'
            ext[clave] = f'{bat.group(1)} V {bat.group(2)} Ah'
            if tipo == 'bateria':
                ext['voltaje'] = f'{bat.group(1)} V'
                ext['capacidad'] = f'{bat.group(2)} Ah'

    return {'columnas': {k: v for k, v in col.items() if v}, 'extras': {k: v for k, v in ext.items() if v}}


def sugerencias(tipo, columnas, extras, hoy=None):
    """Mejoras que tienen sentido según la ficha (reglas fijas, sin IA)."""
    from datetime import date
    hoy = hoy or date.today()
    s = []

    def _n(v):
        try:
            return float(str(v).replace(',', '.').replace('%', '').strip())
        except (TypeError, ValueError):
            return None

    libres = _n(extras.get('ram_ranuras_libres'))
    if tipo in ('computador', 'portatil') and libres and libres > 0:
        s.append({'titulo': 'Ampliar la memoria RAM',
                  'detalle': f'Tiene {int(libres)} ranura(s) libre(s): se puede agregar un módulo sin quitar el actual.',
                  'componente': 'Memoria RAM'})
    disco = (extras.get('tipo_disco') or columnas.get('almacenamiento') or '').upper()
    if tipo in ('computador', 'portatil') and 'HDD' in disco and 'SSD' not in disco:
        s.append({'titulo': 'Cambiar el disco duro por SSD',
                  'detalle': 'El disco mecánico es la causa más común de lentitud; un SSD lo hace varias veces más rápido.',
                  'componente': 'Disco SSD'})
    desgaste, salud = _n(extras.get('bateria_desgaste')), _n(extras.get('bateria_salud'))
    if (desgaste is not None and desgaste >= 30) or (salud is not None and salud <= 80):
        s.append({'titulo': 'Cambiar la batería',
                  'detalle': f"La batería conserva {int(salud) if salud is not None else int(100 - desgaste)}% de su capacidad original.",
                  'componente': 'Batería'})
    ultimo = extras.get('baterias_ultimo_cambio') or extras.get('fecha_instalacion')
    if tipo in ('ups', 'bateria') and ultimo:
        try:
            antig = (hoy - date.fromisoformat(str(ultimo)[:10])).days / 365
        except ValueError:
            antig = None
        if antig is not None and antig >= 2:
            s.append({'titulo': 'Cambiar las baterías de la UPS' if tipo == 'ups' else 'Cambiar la batería',
                      'detalle': f'Tienen {antig:.1f} años; las baterías de plomo-ácido duran entre 2 y 3 años.',
                      'componente': 'Baterías de la UPS' if tipo == 'ups' else 'Batería'})
    so = (columnas.get('sistema_operativo') or '').lower()
    if 'windows 10' in so or 'windows 8' in so or 'windows 7' in so:
        s.append({'titulo': 'Actualizar a Windows 11',
                  'detalle': 'Esa versión de Windows ya no recibe actualizaciones de seguridad.',
                  'componente': 'Sistema operativo'})
    return s
