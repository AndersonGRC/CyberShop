"""Servicio Técnico: carpetas por empresa.

Los equipos de una empresa (los computadores de sus funcionarios) van en la
carpeta de esa empresa; los de personas —los «computadores normales»— en
«Particulares» (equipo sin empresa).

Al importar fichas en Excel o PDF, a qué empresa pertenece cada equipo se decide
primero con reglas (forma jurídica, palabras de empresa, nombres de persona) y,
si el nombre es dudoso o el documento no dice la empresa con su etiqueta, con la
IA del propio negocio y SOLO la local (servicio_tecnico_ia.identificar_empresa):
los nombres no salen a la nube. Lo que decida siempre se puede corregir.
"""
import re
import unicodedata

from database import get_db_cursor

PARTICULARES = 'Particulares'

# Lo que no dice una empresa: equipos de una persona o sin dueño claro.
_GENERICOS = {
    'na', 'n a', 'no aplica', 'ninguna', 'ninguno', 'sin empresa', 'particular', 'particulares', 'personal',
    'persona natural', 'natural', 'cliente', 'clientes', 'cliente general', 'general', 'varios', 'varias', 'otro',
    'otros', 'otra', 'propio', 'propia', 'independiente', 'hogar', 'casa', 'consumidor final', 'publico', 'x', 'xx',
    'xxx', 'no', 'si', 'sin', 'desconocido', 'pendiente', 'empresa', 'nombre', 'usuario', 'equipo', 'n d', 'nd'}

# Formas jurídicas (ya sin puntos: «S.A.S.» → «sas»).
_FORMAS = {'sas', 'sa', 'ltda', 'limitada', 'eu', 'sca', 'scs', 'cia', 'inc', 'corp', 'llc', 'ltd', 'gmbh', 'srl',
           'bic', 'esp', 'sl', 'slu', 'spa', 'plc'}

_PALABRAS_EMPRESA = {
    'grupo', 'group', 'corporacion', 'fundacion', 'asociacion', 'cooperativa', 'clinica', 'hospital', 'ips', 'eps',
    'colegio', 'universidad', 'instituto', 'institucion', 'alcaldia', 'gobernacion', 'secretaria', 'ministerio',
    'banco', 'constructora', 'construcciones', 'distribuidora', 'distribuciones', 'comercializadora', 'inversiones',
    'soluciones', 'servicios', 'ingenieria', 'consultores', 'consultoria', 'laboratorio', 'laboratorios', 'drogueria',
    'ferreteria', 'panaderia', 'restaurante', 'hotel', 'almacen', 'almacenes', 'tienda', 'taller', 'industrias',
    'importadora', 'exportadora', 'agencia', 'empresa', 'compania', 'sociedad', 'holding', 'logistica',
    'transportes', 'tecnologia', 'tecnologias', 'systems', 'solutions', 'medical', 'abogados', 'asociados',
    'notaria', 'parroquia', 'iglesia', 'club', 'academia', 'editorial', 'impresiones', 'publicidad',
    'comunicaciones', 'telecomunicaciones', 'seguros', 'energia', 'minera', 'petroleos', 'agropecuaria',
    'alimentos', 'textiles', 'confecciones', 'inmobiliaria', 'conjunto', 'edificio', 'hijos', 'hermanos',
    'unidad', 'ese', 'entidad', 'cooperativo', 'internacional', 'nacional', 'colombia', 'ltda', 'store', 'shop',
    'center', 'centro', 'studio', 'estudio', 'farmacia', 'optica', 'veterinaria', 'odontologia', 'jardin'}

# Una sola palabra larga que empieza así suele ser una empresa («TECNOSERVICIOS»).
_PREFIJOS_EMPRESA = ('tecno', 'inver', 'distri', 'constru', 'electro', 'farma', 'pharma', 'agro', 'multi', 'servi',
                     'ingen', 'comerci', 'industri', 'import', 'export', 'logist', 'transport', 'soluci', 'sistem',
                     'digit', 'micro', 'compu', 'info', 'tele', 'auto', 'metal', 'plast', 'quimi', 'alimen',
                     'textil', 'inmobili', 'cyber', 'ciber', 'data', 'medic')

_NOMBRES_PILA = set('''
aaron abel abelardo abigail adela adelaida adolfo adrian adriana agustin aida alba albeiro alberto alcira aldemar
alejandra alejandro alexander alexandra alexis alfonso alfredo alicia alirio alvaro amalia amanda amparo ana anderson
andrea andres angel angela angelica anibal antonio armando arturo aura aurora beatriz benjamin bernardo bertha blanca
brayan brenda camila camilo carlos carmen carmenza carolina catalina cecilia cesar clara claudia constanza cristian
cristina cristobal daniel daniela danna dana dario david deisy diana diego dora doris duvan edgar edilberto edison edna
eduardo edwin elena eliana elizabeth elsa elkin emilio emma enrique erika ernesto esperanza esteban estefania estela
eugenia eva fabian fabio federico felipe fernanda fernando flor francisco freddy gabriel gabriela german gilberto gina
gladys gloria gonzalo graciela guillermo gustavo harold hector helena henry hernan hernando hugo humberto ignacio ingrid
ines irma isabel isabella ivan jaime jairo javier jefferson jenifer jennifer jessica jesus jhon jhonatan jhonny jimena
joaquin johan john johnny jonathan jorge jose josefina juan juana julian juliana julio karen karina katherine kelly
laura leidy leonardo leonel lida liliana lina lorena lucia luis luisa luz manuel marcela marco marcos margarita maria
mariana maribel mario marisol marta martha martin mateo mauricio mayerly melissa mercedes miguel milena miriam monica
nancy natalia nelson nestor nicolas nidia nora norma nubia olga omar orlando oscar pablo paola patricia paula pedro
piedad pilar rafael ramiro ramon raul rebeca ricardo roberto rocio rodrigo rodolfo rosa rosalba ruben ruth samuel
sandra santiago sara sebastian sergio silvia simon sofia sonia stella stiven steven susana tatiana teresa tomas
valentina valeria vanessa vicente victor victoria viviana walter wilmer william wilson ximena yamile yaneth yesenia
yolanda yuli yuliana yurany zulma
'''.split())

_APELLIDOS = set('''
acosta aguilar aguirre alvarez arango arias avila barrera bautista becerra beltran benavides bermudez bernal blanco
bolivar bonilla bustos caballero cabrera caicedo calderon camacho campos cano cardenas cardona carrillo castano
castillo castro chaparro cifuentes contreras cordoba correa cortes cruz cuellar delgado diaz duarte duque escobar
espinosa estrada fajardo fernandez florez franco fuentes gaitan galeano galindo gallego garcia garzon gaviria gil
giraldo gomez gonzalez granados guerrero guevara gutierrez guzman henao hernandez herrera hoyos ibarra jaramillo
jimenez lara leon lopez lozano luna marin marquez martinez medina mejia melo mendez mendoza mesa molina montoya mora
morales moreno munoz murillo nieto nino nunez ocampo orozco ortega ortiz osorio ospina pacheco padilla palacios pardo
parra pena perdomo perez pineda pinto pinzon pulido quintero quiroga ramirez ramos restrepo reyes rincon rios rivera
robayo rodriguez rojas romero rubio ruiz salazar salcedo samper sanchez sandoval sarmiento serna serrano serrato sierra
silva solano sosa suarez tellez torres trujillo uribe valencia valero vanegas vargas vasquez vega velasquez velez vera
villa villamizar villegas zapata zuluaga
'''.split())


def plano(texto):
    """minúsculas, sin tildes ni puntos («S.A.S.» → «sas»), signos → espacio."""
    t = unicodedata.normalize('NFD', str(texto or '').lower())
    t = ''.join(ch for ch in t if unicodedata.category(ch) != 'Mn')
    t = t.replace('.', '')
    t = re.sub(r'[^a-z0-9&]+', ' ', t).replace('&', ' & ')
    salida, en_racha = [], False
    for p in t.split():                      # letras sueltas seguidas se juntan: «s a s» → «sas»
        if len(p) == 1 and p.isalpha():
            if en_racha:
                salida[-1] += p
            else:
                salida.append(p)
            en_racha = True
        else:
            salida.append(p)
            en_racha = False
    return ' '.join(salida)


def _sin_nit(texto):
    return re.sub(r'(?i)[\s,;-]*\bnit\b.*$', '', str(texto or '')).strip()


def clave(nombre):
    """Para no repetir carpetas: «TECNOSERVICIOS S.A.S.» = «Tecnoservicios SAS» = «tecnoservicios»."""
    palabras = plano(_sin_nit(nombre)).split()
    while palabras and (palabras[-1] in _FORMAS or palabras[-1] in ('y', '&')):
        palabras.pop()
    if len(palabras) >= 3 and palabras[-2:] == ['en', 'c'] and palabras[-3] == 's':
        palabras = palabras[:-3]
    return ' '.join(palabras)[:160]


def nombre_visible(nombre):
    """El nombre como lo escribió el documento, sin NIT ni signos sueltos."""
    return ' '.join(_sin_nit(nombre).split()).strip(' ,;:-–')[:160]


def clasificar(nombre, negocio=''):
    """('empresa' | 'persona' | 'generico' | 'dudoso', motivo) solo con reglas."""
    c = clave(nombre)
    texto = plano(nombre)
    if not c or c in _GENERICOS or len(c) < 2:
        return 'generico', 'No dice el nombre de una empresa.'
    if negocio and c == clave(negocio):
        return 'generico', 'Es el nombre de tu propio negocio (el taller).'
    tokens = texto.split()
    if any(t in _FORMAS for t in tokens[1:]) or re.search(r'\bnit\b', texto) or 's en c' in texto:
        return 'empresa', 'Tiene forma jurídica (S.A.S., LTDA…) o NIT.'
    palabras = c.split()
    if any(p in _PALABRAS_EMPRESA for p in palabras):
        return 'empresa', 'Tiene palabras de empresa.'
    if re.search(r'\d', c):
        return 'dudoso', 'No se sabe si es una empresa o una persona.'
    pila = sum(1 for p in palabras if p in _NOMBRES_PILA)
    apellidos = sum(1 for p in palabras if p in _APELLIDOS)
    if 2 <= len(palabras) <= 5 and pila and pila + apellidos >= max(2, len(palabras) - 1):
        return 'persona', 'Es el nombre de una persona.'
    if len(palabras) == 1:
        if palabras[0] in _NOMBRES_PILA or palabras[0] in _APELLIDOS:
            return 'persona', 'Es el nombre de una persona.'
        if len(palabras[0]) >= 8 and palabras[0].startswith(_PREFIJOS_EMPRESA):
            return 'empresa', 'Es un nombre de empresa.'
    return 'dudoso', 'No se sabe si es una empresa o una persona.'


_BARRA_FICHA = re.compile(r'EQUIPO\s+ASIGNADO\s+A\s+([^\n|]+)', re.I)


def titular_de_ficha(texto):
    """(asignado a, empresa) de la barra «EQUIPO ASIGNADO A PERSONA - EMPRESA»
    de las fichas del taller (PDF o Excel); (None, None) si no la tiene."""
    m = _BARRA_FICHA.search(texto or '')
    if not m:
        return None, None
    titulo = ' '.join(m.group(1).split()).strip(' -')
    if not titulo:
        return None, None
    if ' - ' in titulo:
        asignado, empresa = [x.strip() for x in titulo.rsplit(' - ', 1)]
        return asignado or None, empresa or None
    return titulo, None


# ── Base de datos ───────────────────────────────────────────────
def listar(incluir_vacias=False):
    """Carpetas para la pantalla de equipos: [{id, nombre, equipos}] + particulares."""
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT x.id, x.nombre, COUNT(e.id) AS equipos
                       FROM st_empresas x LEFT JOIN st_equipos e ON e.empresa_id = x.id AND e.activo
                       WHERE x.activo GROUP BY x.id, x.nombre ORDER BY lower(x.nombre)""")
        empresas = [dict(r) for r in cur.fetchall() if incluir_vacias or r['equipos']]
        cur.execute('SELECT COUNT(*) AS n FROM st_equipos WHERE activo AND empresa_id IS NULL')
        particulares = cur.fetchone()['n']
    return {'empresas': empresas, 'particulares': particulares,
            'total': particulares + sum(e['equipos'] for e in empresas)}


def obtener(empresa_id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute('SELECT id, nombre, nit, crm_contacto_id FROM st_empresas WHERE id = %s AND activo', (empresa_id,))
        fila = cur.fetchone()
    return dict(fila) if fila else None


def por_claves(cur, claves):
    """{clave: {id, nombre}} de las carpetas activas con esas claves."""
    claves = sorted({c for c in claves if c})
    if not claves:
        return {}
    cur.execute('SELECT id, nombre, clave FROM st_empresas WHERE activo AND clave = ANY(%s)', (claves,))
    return {r['clave']: {'id': r['id'], 'nombre': r['nombre']} for r in cur.fetchall()}


def obtener_o_crear(cur, nombre, nit=None, crm_contacto_id=None, usuario_id=None):
    """(id, creada) de la carpeta de esa empresa; la crea si no existe."""
    nombre = nombre_visible(nombre)
    c = clave(nombre)
    if not c:
        raise ValueError('Falta el nombre de la empresa.')
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('st_empresas'))")
    cur.execute('SELECT id FROM st_empresas WHERE activo AND clave = %s', (c,))
    fila = cur.fetchone()
    if fila:
        return (fila['id'] if isinstance(fila, dict) else fila[0]), False
    cur.execute("""INSERT INTO st_empresas (nombre, clave, nit, crm_contacto_id, creado_por)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (nombre, c, (nit or None) and str(nit)[:30], crm_contacto_id, usuario_id))
    fila = cur.fetchone()
    return (fila['id'] if isinstance(fila, dict) else fila[0]), True
