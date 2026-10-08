"""Servicio Técnico: equipos de los clientes, órdenes de servicio y bitácora.

Tablas (BD del propio cliente; ver `DDL`):
  st_equipos       ficha de cada equipo atendido (columnas comunes + extras del tipo)
  st_cambios       piezas cambiadas o agregadas (batería, RAM, disco…) con próxima revisión
  st_ordenes       orden de servicio: recepción → diagnóstico → cotización → reparación → entrega
  st_eventos       bitácora de la orden (cambios de estado, notas, mensajes)
  st_seguimientos  alertas programadas para el cliente y el dueño (F2)

El cliente es un contacto del CRM (`crm_contactos`): no hay otra tabla de
clientes. No se ponen llaves foráneas hacia el CRM para no cambiar cómo se
comporta el CRM al borrar un contacto (allí el borrado es lógico).

La migración `CyberShopAdmin/migrations/tenant/0018_servicio_tecnico.sql`
crea las mismas tablas; si aún no llegó a la base del cliente, `asegurar_tablas`
las crea al primer uso. Las dos definiciones deben ser idénticas (lo vigila
tests/test_servicio_tecnico.py).
"""

import base64
import hashlib
import os
import re
import secrets
from datetime import date, timedelta

from flask import current_app

from database import get_db_cursor
from services import servicio_tecnico_tipos as tipos

DDL_0018 = """
CREATE TABLE IF NOT EXISTS st_equipos (
    id                    SERIAL       PRIMARY KEY,
    crm_contacto_id       INTEGER      NOT NULL,
    tipo                  VARCHAR(30)  NOT NULL,
    marca                 VARCHAR(80),
    modelo                VARCHAR(120),
    serial                VARCHAR(120),
    imei                  VARCHAR(20),
    color                 VARCHAR(40),
    sistema_operativo     VARCHAR(120),
    procesador            VARCHAR(160),
    ram                   VARCHAR(60),
    almacenamiento        VARCHAR(120),
    pantalla              VARCHAR(80),
    extras                JSONB        NOT NULL DEFAULT '{}'::jsonb,
    info_sistema_original TEXT,
    resumen_ia            TEXT,
    sugerencias_ia        JSONB,
    notas                 TEXT,
    activo                BOOLEAN      NOT NULL DEFAULT TRUE,
    creado_por            INTEGER,
    creado_en             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    actualizado_en        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_st_equipos_contacto ON st_equipos (crm_contacto_id);
CREATE INDEX IF NOT EXISTS ix_st_equipos_serial ON st_equipos (lower(serial));
CREATE INDEX IF NOT EXISTS ix_st_equipos_imei ON st_equipos (imei);

CREATE TABLE IF NOT EXISTS st_ordenes (
    id                SERIAL        PRIMARY KEY,
    numero            VARCHAR(20)   UNIQUE,
    equipo_id         INTEGER       NOT NULL REFERENCES st_equipos(id),
    crm_contacto_id   INTEGER       NOT NULL,
    estado            VARCHAR(20)   NOT NULL DEFAULT 'recibido',
    falla_reportada   TEXT          NOT NULL,
    estado_fisico     TEXT,
    accesorios        TEXT,
    clave_cifrada     TEXT,
    diagnostico       TEXT,
    prediagnostico_ia TEXT,
    cotizacion_id     INTEGER,
    tecnico_id        INTEGER,
    valor_estimado    NUMERIC(14,2),
    valor_final       NUMERIC(14,2),
    fecha_recibido    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    fecha_promesa     DATE,
    fecha_listo       TIMESTAMPTZ,
    fecha_entregado   TIMESTAMPTZ,
    garantia_dias     INTEGER       NOT NULL DEFAULT 30,
    garantia_hasta    DATE,
    token_publico     VARCHAR(48)   NOT NULL UNIQUE,
    creado_por        INTEGER,
    creado_en         TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    actualizado_en    TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_st_ordenes_estado ON st_ordenes (estado);
CREATE INDEX IF NOT EXISTS ix_st_ordenes_equipo ON st_ordenes (equipo_id);
CREATE INDEX IF NOT EXISTS ix_st_ordenes_contacto ON st_ordenes (crm_contacto_id);
CREATE INDEX IF NOT EXISTS ix_st_ordenes_cotizacion ON st_ordenes (cotizacion_id);

CREATE TABLE IF NOT EXISTS st_eventos (
    id          BIGSERIAL    PRIMARY KEY,
    orden_id    INTEGER      REFERENCES st_ordenes(id),
    equipo_id   INTEGER      REFERENCES st_equipos(id),
    tipo        VARCHAR(20)  NOT NULL,
    detalle     TEXT,
    usuario_id  INTEGER,
    creado_en   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_st_eventos_orden ON st_eventos (orden_id, creado_en);
CREATE INDEX IF NOT EXISTS ix_st_eventos_equipo ON st_eventos (equipo_id, creado_en);

CREATE TABLE IF NOT EXISTS st_cambios (
    id                SERIAL       PRIMARY KEY,
    equipo_id         INTEGER      NOT NULL REFERENCES st_equipos(id),
    orden_id          INTEGER      REFERENCES st_ordenes(id),
    componente        VARCHAR(80)  NOT NULL,
    detalle           TEXT,
    fecha             DATE         NOT NULL DEFAULT CURRENT_DATE,
    proxima_revision  DATE,
    creado_por        INTEGER,
    creado_en         TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_st_cambios_equipo ON st_cambios (equipo_id);
CREATE INDEX IF NOT EXISTS ix_st_cambios_revision ON st_cambios (proxima_revision);

CREATE TABLE IF NOT EXISTS st_seguimientos (
    id                SERIAL       PRIMARY KEY,
    orden_id          INTEGER      REFERENCES st_ordenes(id),
    equipo_id         INTEGER      REFERENCES st_equipos(id),
    cambio_id         INTEGER      REFERENCES st_cambios(id),
    cotizacion_id     INTEGER,
    crm_contacto_id   INTEGER,
    tipo              VARCHAR(40)  NOT NULL,
    fecha_programada  DATE         NOT NULL,
    canal             VARCHAR(20),
    estado            VARCHAR(20)  NOT NULL DEFAULT 'pendiente',
    calificacion      SMALLINT,
    comentario        TEXT,
    hecho_por         INTEGER,
    hecho_en          TIMESTAMPTZ,
    creado_en         TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_st_seguimientos_pendientes ON st_seguimientos (estado, fecha_programada);
"""

# 0019: solución de la orden y su clasificación (tipo de falla, pieza, tipo de
# solución, etiquetas y resumen del caso) para buscar y consultar el historial.
DDL_0019 = """
ALTER TABLE st_ordenes ADD COLUMN IF NOT EXISTS solucion TEXT;
ALTER TABLE st_ordenes ADD COLUMN IF NOT EXISTS falla_categoria VARCHAR(40);
ALTER TABLE st_ordenes ADD COLUMN IF NOT EXISTS componente VARCHAR(40);
ALTER TABLE st_ordenes ADD COLUMN IF NOT EXISTS solucion_categoria VARCHAR(40);
ALTER TABLE st_ordenes ADD COLUMN IF NOT EXISTS etiquetas VARCHAR(300);
ALTER TABLE st_ordenes ADD COLUMN IF NOT EXISTS resumen_caso VARCHAR(400);
ALTER TABLE st_ordenes ADD COLUMN IF NOT EXISTS clasificacion_fuente VARCHAR(10);
ALTER TABLE st_ordenes ADD COLUMN IF NOT EXISTS clasificado_en TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS ix_st_ordenes_falla_categoria ON st_ordenes (falla_categoria);
CREATE INDEX IF NOT EXISTS ix_st_ordenes_solucion_categoria ON st_ordenes (solucion_categoria);
"""

# 0020: fotos del equipo (en la base del cliente: el código es compartido entre
# tiendas y así cada foto queda solo en la base de su dueño), mantenimientos
# preventivos y correctivos, plan de mantenimiento del equipo y el motivo de los
# recordatorios que se programan a mano.
DDL_0020 = """
CREATE TABLE IF NOT EXISTS st_fotos (
    id           SERIAL       PRIMARY KEY,
    equipo_id    INTEGER      NOT NULL REFERENCES st_equipos(id),
    orden_id     INTEGER      REFERENCES st_ordenes(id),
    momento      VARCHAR(20)  NOT NULL DEFAULT 'ficha',
    descripcion  VARCHAR(200),
    mime         VARCHAR(40)  NOT NULL,
    ancho        INTEGER,
    alto         INTEGER,
    bytes        INTEGER      NOT NULL,
    contenido    BYTEA        NOT NULL,
    miniatura    BYTEA        NOT NULL,
    activo       BOOLEAN      NOT NULL DEFAULT TRUE,
    creado_por   INTEGER,
    creado_en    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_st_fotos_equipo ON st_fotos (equipo_id, activo);

CREATE TABLE IF NOT EXISTS st_mantenimientos (
    id             SERIAL        PRIMARY KEY,
    equipo_id      INTEGER       NOT NULL REFERENCES st_equipos(id),
    orden_id       INTEGER       REFERENCES st_ordenes(id),
    tipo           VARCHAR(20)   NOT NULL,
    fecha          DATE          NOT NULL DEFAULT CURRENT_DATE,
    descripcion    TEXT          NOT NULL,
    hallazgos      TEXT,
    tecnico_id     INTEGER,
    costo          NUMERIC(14,2),
    proxima_fecha  DATE,
    creado_por     INTEGER,
    creado_en      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_st_mantenimientos_equipo ON st_mantenimientos (equipo_id, fecha);

ALTER TABLE st_equipos ADD COLUMN IF NOT EXISTS mant_cada_meses SMALLINT;
ALTER TABLE st_equipos ADD COLUMN IF NOT EXISTS mant_proximo DATE;
ALTER TABLE st_seguimientos ADD COLUMN IF NOT EXISTS motivo VARCHAR(300);
CREATE INDEX IF NOT EXISTS ix_st_seguimientos_equipo ON st_seguimientos (equipo_id, estado);
"""

# 0021: documentos del equipo (PDF, Excel, imágenes de fichas) y lotes de
# importación («Traer desde Excel o PDF»). Un lote se puede deshacer: lo que
# creó queda activo = FALSE (por eso st_mantenimientos gana `activo`); nada se
# borra. `importacion_id` dice de qué lote salió cada equipo y mantenimiento.
DDL_0021 = """
CREATE TABLE IF NOT EXISTS st_importaciones (
    id              SERIAL       PRIMARY KEY,
    estado          VARCHAR(20)  NOT NULL DEFAULT 'leyendo',
    archivos        JSONB        NOT NULL DEFAULT '[]'::jsonb,
    filas           JSONB        NOT NULL DEFAULT '[]'::jsonb,
    ajustes         JSONB        NOT NULL DEFAULT '{}'::jsonb,
    resultado       JSONB,
    creado_por      INTEGER,
    creado_en       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    actualizado_en  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    importado_por   INTEGER,
    importado_en    TIMESTAMPTZ,
    deshecho_por    INTEGER,
    deshecho_en     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_st_importaciones_creado ON st_importaciones (creado_en);

CREATE TABLE IF NOT EXISTS st_documentos (
    id              SERIAL        PRIMARY KEY,
    equipo_id       INTEGER       REFERENCES st_equipos(id),
    orden_id        INTEGER       REFERENCES st_ordenes(id),
    importacion_id  INTEGER       REFERENCES st_importaciones(id),
    nombre          VARCHAR(200)  NOT NULL,
    descripcion     VARCHAR(200),
    mime            VARCHAR(120)  NOT NULL,
    bytes           INTEGER       NOT NULL,
    huella          VARCHAR(64)   NOT NULL,
    contenido       BYTEA         NOT NULL,
    texto           TEXT,
    activo          BOOLEAN       NOT NULL DEFAULT TRUE,
    creado_por      INTEGER,
    creado_en       TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_st_documentos_equipo ON st_documentos (equipo_id, activo);
CREATE INDEX IF NOT EXISTS ix_st_documentos_importacion ON st_documentos (importacion_id);
CREATE INDEX IF NOT EXISTS ix_st_documentos_huella ON st_documentos (huella);

ALTER TABLE st_equipos ADD COLUMN IF NOT EXISTS importacion_id INTEGER;
ALTER TABLE st_mantenimientos ADD COLUMN IF NOT EXISTS importacion_id INTEGER;
ALTER TABLE st_mantenimientos ADD COLUMN IF NOT EXISTS activo BOOLEAN NOT NULL DEFAULT TRUE;
CREATE INDEX IF NOT EXISTS ix_st_equipos_importacion ON st_equipos (importacion_id);
"""

# Lo que asegurar_tablas crea si las migraciones aún no llegaron (en orden).
DDL = DDL_0018 + DDL_0019 + DDL_0020 + DDL_0021

TABLAS = ('st_equipos', 'st_ordenes', 'st_eventos', 'st_cambios', 'st_seguimientos',
          'st_fotos', 'st_mantenimientos', 'st_importaciones', 'st_documentos')

# ── Estados de la orden ──────────────────────────────────────────
# (código, nombre, ícono, tono del chip)
ESTADOS = [
    ('recibido', 'Recibido', 'inbox', 'info'),
    ('diagnostico', 'En diagnóstico', 'stethoscope', 'info'),
    ('cotizado', 'Cotizado', 'file-invoice-dollar', 'aviso'),
    ('aprobado', 'Aprobado', 'thumbs-up', 'marca'),
    ('reparacion', 'En reparación', 'tools', 'marca'),
    ('listo', 'Listo para entregar', 'check-circle', 'exito'),
    ('entregado', 'Entregado', 'handshake', 'neutro'),
    ('garantia', 'En garantía', 'shield-alt', 'aviso'),
    ('cancelado', 'Cancelado', 'ban', 'peligro'),
]
ESTADO_POR_CODIGO = {e[0]: e for e in ESTADOS}
# Camino normal (barra de pasos de la orden).
PASOS = ['recibido', 'diagnostico', 'cotizado', 'aprobado', 'reparacion', 'listo', 'entregado']
# Estados en los que el equipo sigue en el taller.
ABIERTOS = ('recibido', 'diagnostico', 'cotizado', 'aprobado', 'reparacion', 'listo', 'garantia')

TRANSICIONES = {
    'recibido': ('diagnostico', 'cotizado', 'reparacion', 'cancelado'),
    'diagnostico': ('cotizado', 'reparacion', 'listo', 'cancelado'),
    # Cotización rechazada: el equipo se devuelve («listo» para recoger).
    'cotizado': ('aprobado', 'listo', 'cancelado'),
    'aprobado': ('reparacion', 'cancelado'),
    'reparacion': ('listo', 'cancelado'),
    'listo': ('entregado', 'reparacion'),
    'entregado': ('garantia',),
    'garantia': ('reparacion', 'listo'),
    'cancelado': (),
}

GARANTIA_DIAS_DEFECTO = 30


class ErrorServicio(ValueError):
    """Error de validación que se le muestra al usuario tal cual."""


# ── Tablas ───────────────────────────────────────────────────────
_LISTAS = set()


def asegurar_tablas():
    """Crea las tablas si la migración aún no llegó a esta base (una vez por
    proceso y base). Devuelve True si están listas."""
    from database import _current_db_name
    db = _current_db_name()
    if db in _LISTAS:
        return True
    try:
        with get_db_cursor() as cur:
            cur.execute(DDL)
        _LISTAS.add(db)
        return True
    except Exception as exc:  # noqa: BLE001
        try:
            current_app.logger.error(f'servicio_tecnico: no se pudieron crear las tablas: {exc}')
        except Exception:
            pass
        return False


# ── Validaciones ────────────────────────────────────────────────
def imei_valido(imei):
    """15 dígitos y dígito de control (Luhn)."""
    digitos = ''.join(ch for ch in str(imei or '') if ch.isdigit())
    if len(digitos) != 15:
        return False
    total = 0
    for i, ch in enumerate(digitos):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _texto(valor, largo):
    valor = (valor or '').strip() if isinstance(valor, str) else ('' if valor is None else str(valor).strip())
    return valor[:largo] or None


def _numero(valor):
    if valor in (None, ''):
        return None
    try:
        limpio = str(valor).replace('$', '').replace(' ', '').replace('.', '').replace(',', '.')
        n = float(limpio)
    except ValueError:
        raise ErrorServicio('El valor debe ser un número.')
    if n < 0:
        raise ErrorServicio('El valor no puede ser negativo.')
    return round(n, 2)


def _fecha(valor):
    if not valor:
        return None
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        raise ErrorServicio('Fecha no válida.')


# ── Clave de desbloqueo (cifrada) ───────────────────────────────
def _llave_clave():
    """32 bytes: KMS_KEY si la instancia la tiene; si no, derivada de la
    SECRET_KEY de la instancia (solo esta instancia puede leerla)."""
    raw = os.getenv('KMS_KEY', '')
    if raw:
        try:
            llave = base64.b64decode(raw)
            if len(llave) == 32:
                return llave
        except Exception:  # noqa: BLE001
            pass
    secreto = str(current_app.config.get('SECRET_KEY') or '')
    if not secreto:
        raise ErrorServicio('No se puede guardar la clave: la instancia no tiene SECRET_KEY.')
    return hashlib.sha256(('st-clave-v1:' + secreto).encode('utf-8')).digest()


def cifrar_clave(texto):
    texto = (texto or '').strip()
    if not texto:
        return None
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = secrets.token_bytes(12)
    ct = AESGCM(_llave_clave()).encrypt(nonce, texto[:200].encode('utf-8'), None)
    return base64.b64encode(nonce + ct).decode('ascii')


def descifrar_clave(cifrada):
    if not cifrada:
        return None
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        datos = base64.b64decode(cifrada)
        return AESGCM(_llave_clave()).decrypt(datos[:12], datos[12:], None).decode('utf-8')
    except Exception:  # noqa: BLE001
        return None


# ── Clientes (contactos del CRM) ────────────────────────────────
def buscar_clientes(q, limite=12):
    q = (q or '').strip()
    if len(q) < 2:
        return []
    patron = f'%{q.lower()}%'
    digitos = ''.join(ch for ch in q if ch.isdigit())
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT id, nombre, empresa, email, telefono, whatsapp
            FROM crm_contactos
            WHERE COALESCE(activo, TRUE)
              AND (lower(nombre) LIKE %s OR lower(COALESCE(empresa,'')) LIKE %s
                   OR lower(COALESCE(email,'')) LIKE %s
                   OR (%s <> '' AND (regexp_replace(COALESCE(telefono,''), '\\D', '', 'g') LIKE %s
                                  OR regexp_replace(COALESCE(whatsapp,''), '\\D', '', 'g') LIKE %s)))
            ORDER BY nombre LIMIT %s
        """, (patron, patron, patron, digitos, f'%{digitos}%', f'%{digitos}%', limite))
        return [dict(r) for r in cur.fetchall()]


def obtener_cliente(contacto_id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT id, nombre, empresa, email, telefono, whatsapp, direccion, ciudad
                       FROM crm_contactos WHERE id = %s""", (contacto_id,))
        fila = cur.fetchone()
    return dict(fila) if fila else None


def crear_cliente(cur, datos):
    nombre = _texto(datos.get('nombre'), 150)
    if not nombre:
        raise ErrorServicio('Escribe el nombre del cliente.')
    telefono = _texto(datos.get('telefono'), 40)
    whatsapp = _texto(datos.get('whatsapp'), 40) or telefono
    email = _texto(datos.get('email'), 150)
    if email and '@' not in email:
        raise ErrorServicio('El correo del cliente no es válido.')
    cur.execute("""
        INSERT INTO crm_contactos (tipo, nombre, email, telefono, whatsapp, direccion, ciudad, origen, notas)
        VALUES ('cliente', %s, %s, %s, %s, %s, %s, 'servicio_tecnico', NULL)
        RETURNING id
    """, (nombre, email, telefono, whatsapp, _texto(datos.get('direccion'), 200),
          _texto(datos.get('ciudad'), 80)))
    return cur.fetchone()[0]


# ── Equipos ─────────────────────────────────────────────────────
_COLUMNAS_EQUIPO = ('marca', 'modelo', 'serial', 'imei', 'color', 'sistema_operativo',
                    'procesador', 'ram', 'almacenamiento', 'pantalla')
_LARGOS = {'marca': 80, 'modelo': 120, 'serial': 120, 'imei': 20, 'color': 40,
           'sistema_operativo': 120, 'procesador': 160, 'ram': 60, 'almacenamiento': 120,
           'pantalla': 80}


def _datos_equipo(datos):
    tipo = (datos.get('tipo') or '').strip()
    if not tipos.es_valido(tipo):
        raise ErrorServicio('Escoge el tipo de equipo.')
    limpio = {'tipo': tipo}
    for col in _COLUMNAS_EQUIPO:
        limpio[col] = _texto(datos.get(col), _LARGOS[col])
    if limpio['imei']:
        limpio['imei'] = ''.join(ch for ch in limpio['imei'] if ch.isdigit())
        if not imei_valido(limpio['imei']):
            raise ErrorServicio('El IMEI no es válido: debe tener 15 dígitos y su dígito de control '
                                '(márcalo con *#06# en el celular).')
    extras_entrada = datos.get('extras')
    if not isinstance(extras_entrada, dict):
        extras_entrada = {c: datos.get('extra_' + c) for c in tipos.claves_extra(tipo)}
    limpio['extras'] = tipos.limpiar_extras(tipo, extras_entrada)
    limpio['notas'] = _texto(datos.get('notas'), 2000)
    return limpio


def _serial_repetido(cur, contacto_id, serial, excluir_id=None):
    if not serial:
        return False
    cur.execute("""SELECT 1 FROM st_equipos WHERE crm_contacto_id = %s AND lower(serial) = lower(%s)
                   AND activo AND (%s IS NULL OR id <> %s) LIMIT 1""",
                (contacto_id, serial, excluir_id, excluir_id))
    return cur.fetchone() is not None


def crear_equipo(cur, contacto_id, datos, usuario_id=None):
    import json
    d = _datos_equipo(datos)
    if _serial_repetido(cur, contacto_id, d['serial']):
        raise ErrorServicio('Este cliente ya tiene un equipo con ese serial. Escógelo en la lista.')
    # Texto pegado en el asistente (ya sin datos personales) y su resumen.
    from services.servicio_tecnico_lector import limpiar_personales
    info = limpiar_personales(datos.get('info_sistema')) or None
    resumen = _texto(datos.get('resumen_ia'), 800)
    cur.execute(f"""
        INSERT INTO st_equipos (crm_contacto_id, tipo, {', '.join(_COLUMNAS_EQUIPO)}, extras, notas, creado_por,
                                info_sistema_original, resumen_ia)
        VALUES (%s, %s, {', '.join(['%s'] * len(_COLUMNAS_EQUIPO))}, %s::jsonb, %s, %s, %s, %s)
        RETURNING id
    """, (contacto_id, d['tipo'], *[d[c] for c in _COLUMNAS_EQUIPO], json.dumps(d['extras']),
          d['notas'], usuario_id, info, resumen))
    equipo_id = cur.fetchone()[0]
    _evento(cur, None, equipo_id, 'equipo', f"Equipo registrado: {descripcion_equipo(d)}", usuario_id)
    return equipo_id


def actualizar_equipo(equipo_id, datos, usuario_id=None):
    import json
    d = _datos_equipo(datos)
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute('SELECT crm_contacto_id FROM st_equipos WHERE id = %s FOR UPDATE', (equipo_id,))
        fila = cur.fetchone()
        if not fila:
            raise ErrorServicio('El equipo no existe.')
        if _serial_repetido(cur, fila['crm_contacto_id'], d['serial'], excluir_id=equipo_id):
            raise ErrorServicio('Este cliente ya tiene otro equipo con ese serial.')
        cur.execute(f"""
            UPDATE st_equipos SET tipo = %s, {', '.join(c + ' = %s' for c in _COLUMNAS_EQUIPO)},
                   extras = %s::jsonb, notas = %s, actualizado_en = NOW()
            WHERE id = %s
        """, (d['tipo'], *[d[c] for c in _COLUMNAS_EQUIPO], json.dumps(d['extras']), d['notas'], equipo_id))
        _evento(cur, None, equipo_id, 'equipo', 'Ficha del equipo actualizada', usuario_id)


def descripcion_equipo(e):
    partes = [tipos.nombre(e.get('tipo'))]
    marca_modelo = ' '.join(p for p in (e.get('marca'), e.get('modelo')) if p)
    if marca_modelo:
        partes.append(marca_modelo)
    return ' · '.join(partes)


def obtener_equipo(equipo_id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT e.*, c.nombre AS cliente_nombre, c.email AS cliente_email,
                              c.telefono AS cliente_telefono, c.whatsapp AS cliente_whatsapp
                       FROM st_equipos e LEFT JOIN crm_contactos c ON c.id = e.crm_contacto_id
                       WHERE e.id = %s""", (equipo_id,))
        fila = cur.fetchone()
    return dict(fila) if fila else None


def resumen_equipos_de_contacto(contacto_id):
    """Equipos del cliente para su ficha en el CRM: servicios, orden abierta,
    próximo mantenimiento y recordatorios pendientes."""
    if not asegurar_tablas():
        return []
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT e.id, e.tipo, e.marca, e.modelo, e.serial, e.imei, e.mant_proximo,
                   (SELECT COUNT(*) FROM st_ordenes o WHERE o.equipo_id = e.id) AS ordenes,
                   (SELECT o.estado FROM st_ordenes o WHERE o.equipo_id = e.id ORDER BY o.id DESC LIMIT 1) AS ultimo_estado,
                   (SELECT COUNT(*) FROM st_seguimientos s WHERE s.equipo_id = e.id AND s.estado = 'pendiente') AS recordatorios
            FROM st_equipos e
            WHERE e.crm_contacto_id = %s AND e.activo
            ORDER BY e.actualizado_en DESC LIMIT 30
        """, (contacto_id,))
        filas = [dict(r) for r in cur.fetchall()]
    for f in filas:
        f['descripcion'] = descripcion_equipo(f)
        f['icono'] = tipos.icono(f['tipo'])
        estado = ESTADO_POR_CODIGO.get(f['ultimo_estado'])
        f['estado_nombre'] = estado[1] if estado else None
        f['abierta'] = f['ultimo_estado'] in ABIERTOS
    return filas


def equipos_de_cliente(contacto_id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT id, tipo, marca, modelo, serial, imei FROM st_equipos
                       WHERE crm_contacto_id = %s AND activo ORDER BY actualizado_en DESC""",
                    (contacto_id,))
        return [dict(r) for r in cur.fetchall()]


def listar_equipos(q='', tipo='', limite=200):
    filtros, params = ['e.activo'], []
    if tipo and tipos.es_valido(tipo):
        filtros.append('e.tipo = %s')
        params.append(tipo)
    q = (q or '').strip().lower()
    if q:
        patron = f'%{q}%'
        filtros.append("""(lower(COALESCE(e.marca,'')) LIKE %s OR lower(COALESCE(e.modelo,'')) LIKE %s
                          OR lower(COALESCE(e.serial,'')) LIKE %s OR COALESCE(e.imei,'') LIKE %s
                          OR lower(COALESCE(c.nombre,'')) LIKE %s)""")
        params += [patron] * 5
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(f"""
            SELECT e.id, e.tipo, e.marca, e.modelo, e.serial, e.imei, e.actualizado_en, e.mant_proximo,
                   c.nombre AS cliente_nombre,
                   (SELECT COUNT(*) FROM st_ordenes o WHERE o.equipo_id = e.id) AS ordenes,
                   (SELECT o.estado FROM st_ordenes o WHERE o.equipo_id = e.id
                     ORDER BY o.id DESC LIMIT 1) AS ultimo_estado
            FROM st_equipos e LEFT JOIN crm_contactos c ON c.id = e.crm_contacto_id
            WHERE {' AND '.join(filtros)}
            ORDER BY e.actualizado_en DESC LIMIT %s
        """, (*params, limite))
        return [dict(r) for r in cur.fetchall()]


# ── Piezas cambiadas ────────────────────────────────────────────
def registrar_cambio(equipo_id, datos, usuario_id=None, orden_id=None):
    componente = _texto(datos.get('componente'), 80)
    if not componente:
        raise ErrorServicio('Escribe qué pieza se cambió.')
    fecha = _fecha(datos.get('fecha')) or date.today()
    proxima = _fecha(datos.get('proxima_revision'))
    if proxima and proxima <= fecha:
        raise ErrorServicio('La próxima revisión debe ser posterior a la fecha del cambio.')
    with get_db_cursor() as cur:
        cur.execute("""INSERT INTO st_cambios (equipo_id, orden_id, componente, detalle, fecha,
                                               proxima_revision, creado_por)
                       VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                    (equipo_id, orden_id, componente, _texto(datos.get('detalle'), 1000), fecha,
                     proxima, usuario_id))
        cambio_id = cur.fetchone()[0]
        _evento(cur, orden_id, equipo_id, 'cambio', f'Pieza cambiada: {componente}', usuario_id)
        from services import servicio_tecnico_seguimiento as seg
        seg.al_registrar_cambio(cur, cambio_id, equipo_id, proxima, orden_id)
    return cambio_id


def cambios_de_equipo(equipo_id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT c.id, c.orden_id, c.componente, c.detalle, c.fecha, c.proxima_revision,
                              o.numero AS orden_numero
                       FROM st_cambios c LEFT JOIN st_ordenes o ON o.id = c.orden_id
                       WHERE c.equipo_id = %s ORDER BY c.fecha DESC, c.id DESC""",
                    (equipo_id,))
        return [dict(r) for r in cur.fetchall()]


# ── Órdenes ─────────────────────────────────────────────────────
def crear_orden(datos, usuario_id=None):
    """Crea cliente (si es nuevo), equipo (si es nuevo) y la orden, todo en una
    transacción. Devuelve el id de la orden."""
    falla = _texto(datos.get('falla_reportada'), 4000)
    if not falla:
        raise ErrorServicio('Describe la falla que reporta el cliente.')
    garantia = datos.get('garantia_dias')
    try:
        garantia = int(garantia) if garantia not in (None, '') else GARANTIA_DIAS_DEFECTO
    except ValueError:
        raise ErrorServicio('Los días de garantía deben ser un número.')
    if garantia < 0 or garantia > 3650:
        raise ErrorServicio('Los días de garantía no son válidos.')
    clave = cifrar_clave(datos.get('clave'))

    with get_db_cursor() as cur:
        contacto_id = datos.get('crm_contacto_id')
        if contacto_id:
            cur.execute('SELECT id FROM crm_contactos WHERE id = %s', (contacto_id,))
            if not cur.fetchone():
                raise ErrorServicio('El cliente escogido no existe.')
        else:
            contacto_id = crear_cliente(cur, datos.get('cliente') or {})

        equipo_id = datos.get('equipo_id')
        if equipo_id:
            cur.execute('SELECT crm_contacto_id FROM st_equipos WHERE id = %s AND activo', (equipo_id,))
            fila = cur.fetchone()
            if not fila or int(fila[0]) != int(contacto_id):
                raise ErrorServicio('El equipo escogido no es de este cliente.')
        else:
            equipo_id = crear_equipo(cur, contacto_id, datos.get('equipo') or {}, usuario_id)

        token = secrets.token_urlsafe(24)
        cur.execute("""
            INSERT INTO st_ordenes (equipo_id, crm_contacto_id, falla_reportada, estado_fisico, accesorios,
                                    clave_cifrada, tecnico_id, valor_estimado, fecha_promesa, garantia_dias,
                                    token_publico, creado_por)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (equipo_id, contacto_id, falla, _texto(datos.get('estado_fisico'), 2000),
              _texto(datos.get('accesorios'), 1000), clave, datos.get('tecnico_id') or None,
              _numero(datos.get('valor_estimado')), _fecha(datos.get('fecha_promesa')), garantia,
              token, usuario_id))
        orden_id = cur.fetchone()[0]
        numero = f'OS-{orden_id:06d}'
        cur.execute('UPDATE st_ordenes SET numero = %s WHERE id = %s', (numero, orden_id))
        _evento(cur, orden_id, equipo_id, 'estado', f'Orden {numero} recibida', usuario_id)
        _actividad_crm(cur, contacto_id, 'nota', f'Servicio técnico: {numero} recibida',
                       falla[:500], usuario_id)
    return orden_id


def obtener_orden(orden_id=None, token=None):
    campo, valor = ('o.id', orden_id) if orden_id is not None else ('o.token_publico', token)
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(f"""
            SELECT o.*, e.tipo, e.marca, e.modelo, e.serial, e.imei, e.color,
                   c.nombre AS cliente_nombre, c.email AS cliente_email,
                   c.telefono AS cliente_telefono, c.whatsapp AS cliente_whatsapp,
                   c.direccion AS cliente_direccion, c.ciudad AS cliente_ciudad,
                   u.nombre AS tecnico_nombre
            FROM st_ordenes o
            JOIN st_equipos e ON e.id = o.equipo_id
            LEFT JOIN crm_contactos c ON c.id = o.crm_contacto_id
            LEFT JOIN usuarios u ON u.id = o.tecnico_id
            WHERE {campo} = %s
        """, (valor,))
        fila = cur.fetchone()
    return dict(fila) if fila else None


def listar_ordenes(estado='', q='', tecnico_id=None, abiertas=False, limite=200):
    filtros, params = [], []
    if estado in ESTADO_POR_CODIGO:
        filtros.append('o.estado = %s')
        params.append(estado)
    elif abiertas:
        filtros.append('o.estado = ANY(%s)')
        params.append(list(ABIERTOS))
    if tecnico_id:
        filtros.append('o.tecnico_id = %s')
        params.append(tecnico_id)
    q = (q or '').strip().lower()
    if q:
        patron = f'%{q}%'
        filtros.append("""(lower(o.numero) LIKE %s OR lower(COALESCE(c.nombre,'')) LIKE %s
                          OR lower(COALESCE(e.serial,'')) LIKE %s OR COALESCE(e.imei,'') LIKE %s
                          OR lower(COALESCE(e.marca,'') || ' ' || COALESCE(e.modelo,'')) LIKE %s
                          OR lower(COALESCE(o.falla_reportada,'') || ' ' || COALESCE(o.diagnostico,'') || ' '
                                   || COALESCE(o.solucion,'') || ' ' || COALESCE(o.etiquetas,'')) LIKE %s)""")
        params += [patron] * 6
    donde = ('WHERE ' + ' AND '.join(filtros)) if filtros else ''
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(f"""
            SELECT o.id, o.numero, o.estado, o.fecha_recibido, o.fecha_promesa, o.valor_estimado,
                   o.valor_final, e.tipo, e.marca, e.modelo, c.nombre AS cliente_nombre,
                   u.nombre AS tecnico_nombre
            FROM st_ordenes o
            JOIN st_equipos e ON e.id = o.equipo_id
            LEFT JOIN crm_contactos c ON c.id = o.crm_contacto_id
            LEFT JOIN usuarios u ON u.id = o.tecnico_id
            {donde}
            ORDER BY o.id DESC LIMIT %s
        """, (*params, limite))
        return [dict(r) for r in cur.fetchall()]


def ordenes_de_equipo(equipo_id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT id, numero, estado, falla_reportada, fecha_recibido, fecha_entregado, valor_final,
                              solucion, resumen_caso, falla_categoria
                       FROM st_ordenes WHERE equipo_id = %s ORDER BY id DESC""", (equipo_id,))
        return [dict(r) for r in cur.fetchall()]


def resumen_estados():
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute('SELECT estado, COUNT(*) AS n FROM st_ordenes GROUP BY estado')
        return {r['estado']: r['n'] for r in cur.fetchall()}


def cambiar_estado(orden_id, nuevo, usuario_id=None, nota=None, datos=None):
    """Aplica una transición válida y registra fechas, garantía y bitácora."""
    datos = datos or {}
    if nuevo not in ESTADO_POR_CODIGO:
        raise ErrorServicio('Estado no válido.')
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute('SELECT id, numero, estado, equipo_id, crm_contacto_id, garantia_dias '
                    'FROM st_ordenes WHERE id = %s FOR UPDATE', (orden_id,))
        orden = cur.fetchone()
        if not orden:
            raise ErrorServicio('La orden no existe.')
        actual = orden['estado']
        if nuevo not in TRANSICIONES.get(actual, ()):
            raise ErrorServicio(f'No se puede pasar de «{ESTADO_POR_CODIGO[actual][1]}» '
                                f'a «{ESTADO_POR_CODIGO[nuevo][1]}».')
        sets, params = ['estado = %s', 'actualizado_en = NOW()'], [nuevo]
        garantia_hasta = None
        if nuevo == 'listo':
            sets.append('fecha_listo = NOW()')
        if nuevo == 'entregado':
            valor_final = _numero(datos.get('valor_final'))
            if valor_final is not None:
                sets.append('valor_final = %s')
                params.append(valor_final)
            sets.append('fecha_entregado = NOW()')
            dias = int(orden['garantia_dias'] or 0)
            garantia_hasta = date.today() + timedelta(days=dias) if dias > 0 else None
            sets.append('garantia_hasta = %s')
            params.append(garantia_hasta)
        if datos.get('diagnostico'):
            sets.append('diagnostico = %s')
            params.append(_texto(datos.get('diagnostico'), 4000))
        if datos.get('solucion'):
            sets.append('solucion = %s')
            params.append(_texto(datos.get('solucion'), 4000))
        cur.execute(f"UPDATE st_ordenes SET {', '.join(sets)} WHERE id = %s", (*params, orden_id))
        texto = f"{ESTADO_POR_CODIGO[actual][1]} → {ESTADO_POR_CODIGO[nuevo][1]}"
        if nota:
            texto += f'. {_texto(nota, 1000)}'
        _evento(cur, orden_id, orden['equipo_id'], 'estado', texto, usuario_id)
        _actividad_crm(cur, orden['crm_contacto_id'], 'nota',
                       f"Servicio técnico {orden['numero']}: {ESTADO_POR_CODIGO[nuevo][1]}",
                       texto, usuario_id)
        # Recordatorios que nacen o se cierran con este cambio (misma transacción).
        from services import servicio_tecnico_seguimiento as seg
        seg.al_cambiar_estado(cur, orden, nuevo, garantia_hasta)
    return nuevo


def actualizar_orden(orden_id, datos, usuario_id=None):
    """Campos editables de la orden (no el estado)."""
    sets, params = [], []
    for campo, largo in (('diagnostico', 4000), ('solucion', 4000), ('estado_fisico', 2000), ('accesorios', 1000)):
        if campo in datos:
            sets.append(f'{campo} = %s')
            params.append(_texto(datos.get(campo), largo))
    for campo in ('valor_estimado', 'valor_final'):
        if campo in datos:
            sets.append(f'{campo} = %s')
            params.append(_numero(datos.get(campo)))
    if 'fecha_promesa' in datos:
        sets.append('fecha_promesa = %s')
        params.append(_fecha(datos.get('fecha_promesa')))
    if 'tecnico_id' in datos:
        sets.append('tecnico_id = %s')
        params.append(datos.get('tecnico_id') or None)
    if 'garantia_dias' in datos:
        try:
            dias = int(datos.get('garantia_dias') or 0)
        except ValueError:
            raise ErrorServicio('Los días de garantía deben ser un número.')
        if dias < 0 or dias > 3650:
            raise ErrorServicio('Los días de garantía no son válidos.')
        sets.append('garantia_dias = %s')
        params.append(dias)
    if 'clave' in datos and (datos.get('clave') or '').strip():
        sets.append('clave_cifrada = %s')
        params.append(cifrar_clave(datos.get('clave')))
    if not sets:
        return
    with get_db_cursor() as cur:
        cur.execute(f"UPDATE st_ordenes SET {', '.join(sets)}, actualizado_en = NOW() WHERE id = %s RETURNING equipo_id",
                    (*params, orden_id))
        fila = cur.fetchone()
        if not fila:
            raise ErrorServicio('La orden no existe.')
        _evento(cur, orden_id, fila[0], 'nota', 'Datos de la orden actualizados', usuario_id)


def ver_clave(orden_id, usuario_id):
    """Descifra la clave y deja constancia de quién la vio."""
    with get_db_cursor() as cur:
        cur.execute('SELECT clave_cifrada, equipo_id FROM st_ordenes WHERE id = %s', (orden_id,))
        fila = cur.fetchone()
        if not fila or not fila[0]:
            return None
        _evento(cur, orden_id, fila[1], 'clave', 'Consultó la clave de desbloqueo', usuario_id)
    return descifrar_clave(fila[0])


def agregar_nota(orden_id, texto, usuario_id=None, tipo='nota'):
    texto = _texto(texto, 2000)
    if not texto:
        raise ErrorServicio('Escribe la nota.')
    if tipo not in ('nota', 'llamada', 'whatsapp', 'correo'):
        tipo = 'nota'
    with get_db_cursor() as cur:
        cur.execute('SELECT equipo_id, crm_contacto_id FROM st_ordenes WHERE id = %s', (orden_id,))
        fila = cur.fetchone()
        if not fila:
            raise ErrorServicio('La orden no existe.')
        _evento(cur, orden_id, fila[0], tipo, texto, usuario_id)
        if tipo in ('llamada', 'whatsapp', 'correo'):
            _actividad_crm(cur, fila[1], {'correo': 'email'}.get(tipo, tipo),
                           f'Servicio técnico: {tipo}', texto, usuario_id)


def eventos(orden_id=None, equipo_id=None):
    campo, valor = ('e.orden_id', orden_id) if orden_id is not None else ('e.equipo_id', equipo_id)
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(f"""SELECT e.tipo, e.detalle, e.creado_en, u.nombre AS usuario
                        FROM st_eventos e LEFT JOIN usuarios u ON u.id = e.usuario_id
                        WHERE {campo} = %s ORDER BY e.creado_en DESC, e.id DESC LIMIT 200""", (valor,))
        filas = [dict(r) for r in cur.fetchall()]
    # «correo:listo · …» es la marca que evita repetir el correo; en pantalla sobra.
    for f in filas:
        f['detalle'] = re.sub(r'^correo:\w+ · ', '', f['detalle'] or '')
    return filas


def vincular_cotizacion(orden_id, cotizacion_id, usuario_id=None):
    """Enlaza la cotización a la orden y la pasa a «cotizado» si corresponde."""
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute('SELECT estado FROM st_ordenes WHERE id = %s', (orden_id,))
        fila = cur.fetchone()
        if not fila:
            return
        cur.execute('UPDATE st_ordenes SET cotizacion_id = %s, actualizado_en = NOW() WHERE id = %s',
                    (cotizacion_id, orden_id))
    if fila['estado'] in ('recibido', 'diagnostico'):
        cambiar_estado(orden_id, 'cotizado', usuario_id, nota=f'Cotización #{cotizacion_id}')


def al_aprobar_cotizacion(cotizacion_id, usuario_id=None):
    """La cotización aprobada pasa su orden a «aprobado». No falla nunca: la
    aprobación de la cotización no depende de este módulo."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT to_regclass('public.st_ordenes') AS t")
            if not cur.fetchone()['t']:
                return
            cur.execute("SELECT id FROM st_ordenes WHERE cotizacion_id = %s AND estado = 'cotizado'",
                        (cotizacion_id,))
            ids = [r['id'] for r in cur.fetchall()]
        for oid in ids:
            cambiar_estado(oid, 'aprobado', usuario_id, nota=f'Cotización #{cotizacion_id} aprobada')
    except Exception as exc:  # noqa: BLE001
        try:
            current_app.logger.warning(f'servicio_tecnico: no se pudo aprobar la orden de la cotización {cotizacion_id}: {exc}')
        except Exception:
            pass


def tecnicos():
    from security import ADMIN_STAFF
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT id, nombre FROM usuarios WHERE estado = 'habilitado' AND rol_id = ANY(%s)
                       ORDER BY nombre""", (list(ADMIN_STAFF),))
        return [dict(r) for r in cur.fetchall()]


# ── Bitácora ────────────────────────────────────────────────────
def _evento(cur, orden_id, equipo_id, tipo, detalle, usuario_id=None):
    cur.execute("""INSERT INTO st_eventos (orden_id, equipo_id, tipo, detalle, usuario_id)
                   VALUES (%s, %s, %s, %s, %s)""", (orden_id, equipo_id, tipo, detalle, usuario_id))


def _actividad_crm(cur, contacto_id, tipo, asunto, descripcion, usuario_id=None):
    """Copia a la línea de tiempo del contacto en el CRM. Si falla (contacto
    borrado, columna distinta), no tumba la operación del taller."""
    if not contacto_id:
        return
    try:
        cur.execute('SAVEPOINT st_crm')
        cur.execute("""INSERT INTO crm_actividades (contacto_id, tipo, asunto, descripcion, usuario_id)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (contacto_id, tipo, asunto[:200], descripcion, usuario_id))
        cur.execute('RELEASE SAVEPOINT st_crm')
    except Exception:  # noqa: BLE001
        cur.execute('ROLLBACK TO SAVEPOINT st_crm')


# ── F3: lo que propone la IA y el técnico acepta ────────────────
def aplicar_info(equipo_id, campos, texto=None, resumen=None, sugerencias=None, usuario_id=None):
    """Guarda en la ficha SOLO los campos aceptados (columna o extra_<clave>),
    el texto pegado (sin datos personales), el resumen y las sugerencias."""
    import json
    from services.servicio_tecnico_lector import limpiar_personales
    equipo = obtener_equipo(equipo_id)
    if not equipo:
        raise ErrorServicio('El equipo no existe.')
    datos = {'tipo': equipo['tipo'], 'notas': equipo.get('notas')}
    for col in _COLUMNAS_EQUIPO:
        datos[col] = equipo.get(col)
    extras = dict(equipo.get('extras') or {})
    aceptados = []
    for campo, valor in (campos or {}).items():
        if campo.startswith('extra_'):
            extras[campo[6:]] = valor
            aceptados.append(campo[6:])
        elif campo in _COLUMNAS_EQUIPO:
            datos[campo] = valor
            aceptados.append(campo)
    datos['extras'] = extras
    d = _datos_equipo(datos)                       # mismas validaciones (IMEI, tipos, opciones)
    with get_db_cursor() as cur:
        if _serial_repetido(cur, equipo['crm_contacto_id'], d['serial'], excluir_id=equipo_id):
            raise ErrorServicio('Este cliente ya tiene otro equipo con ese serial.')
        sets = [c + ' = %s' for c in _COLUMNAS_EQUIPO] + ['extras = %s::jsonb', 'actualizado_en = NOW()']
        params = [d[c] for c in _COLUMNAS_EQUIPO] + [json.dumps(d['extras'])]
        if texto is not None:
            sets.append('info_sistema_original = %s')
            params.append(limpiar_personales(texto) or None)
        if resumen is not None:
            sets.append('resumen_ia = %s')
            params.append(_texto(resumen, 800))
        if sugerencias is not None:
            sets.append('sugerencias_ia = %s::jsonb')
            params.append(json.dumps(sugerencias[:8], ensure_ascii=False))
        cur.execute(f"UPDATE st_equipos SET {', '.join(sets)} WHERE id = %s", (*params, equipo_id))
        _evento(cur, None, equipo_id, 'equipo',
                f"Ficha completada desde la información del sistema ({len(aceptados)} campos)"
                if aceptados else 'Información del sistema guardada', usuario_id)
    return aceptados


def guardar_prediagnostico(orden_id, texto, usuario_id=None):
    with get_db_cursor() as cur:
        cur.execute('UPDATE st_ordenes SET prediagnostico_ia = %s, actualizado_en = NOW() WHERE id = %s RETURNING equipo_id',
                    (_texto(texto, 3000), orden_id))
        fila = cur.fetchone()
        if not fila:
            raise ErrorServicio('La orden no existe.')
        _evento(cur, orden_id, fila[0], 'nota', 'Pre-diagnóstico sugerido por la IA', usuario_id)


def orden_abierta_de_equipo(equipo_id):
    with get_db_cursor() as cur:
        cur.execute('SELECT id FROM st_ordenes WHERE equipo_id = %s AND estado = ANY(%s) ORDER BY id DESC LIMIT 1',
                    (equipo_id, list(ABIERTOS)))
        fila = cur.fetchone()
    return fila[0] if fila else None


# ── Registrar un equipo sin orden (ficha, plan y fotos) ─────────
def _cada_meses(valor):
    if valor in (None, ''):
        return 0
    try:
        meses = int(valor)
    except (TypeError, ValueError):
        raise ErrorServicio('La frecuencia del mantenimiento debe ser un número de meses.')
    if meses < 0 or meses > 36:
        raise ErrorServicio('La frecuencia del mantenimiento va de 1 a 36 meses.')
    return meses


def registrar_equipo(datos, usuario_id=None):
    """Cliente (existente o nuevo) + ficha del equipo + plan de mantenimiento,
    en una transacción. Las fotos se guardan aparte (`guardar_fotos`), para que
    una foto dañada no impida registrar el equipo. Devuelve el id del equipo."""
    meses = _cada_meses(datos.get('mant_cada_meses'))
    proximo = _fecha(datos.get('mant_proximo'))
    if proximo and proximo < date.today():
        raise ErrorServicio('La fecha del próximo mantenimiento ya pasó.')
    from services import servicio_tecnico_seguimiento as seg
    if meses and not proximo:
        proximo = seg._sumar_meses(date.today(), meses)
    with get_db_cursor() as cur:
        contacto_id = datos.get('crm_contacto_id')
        if contacto_id:
            cur.execute('SELECT id FROM crm_contactos WHERE id = %s', (contacto_id,))
            if not cur.fetchone():
                raise ErrorServicio('El cliente escogido no existe.')
        else:
            contacto_id = crear_cliente(cur, datos.get('cliente') or {})
        equipo = datos.get('equipo') or {}
        equipo_id = crear_equipo(cur, contacto_id, equipo, usuario_id)
        if meses or proximo:
            cur.execute('UPDATE st_equipos SET mant_cada_meses = %s, mant_proximo = %s WHERE id = %s',
                        (meses or None, proximo, equipo_id))
            if proximo:
                seg.programar(cur, 'mantenimiento', proximo, equipo_id=equipo_id, contacto_id=contacto_id)
        _actividad_crm(cur, contacto_id, 'nota', 'Servicio técnico: equipo registrado',
                       descripcion_equipo(_datos_equipo(equipo)), usuario_id)
    return equipo_id


# ── Fotos del equipo ────────────────────────────────────────────
FOTOS_MAX = 24                         # fotos activas por equipo
FOTO_MAX_BYTES = 15 * 1024 * 1024      # lo que llega del celular, antes de reducirla
FOTO_LADO = 1600                       # lado mayor de la foto guardada
MINI_LADO = 360                        # lado mayor de la miniatura
MOMENTOS_FOTO = [
    ('ficha', 'Ficha del equipo'),
    ('recepcion', 'Al recibirlo'),
    ('etiqueta', 'Etiqueta / placa'),
    ('reparacion', 'Durante la reparación'),
    ('entrega', 'Al entregarlo'),
]
MOMENTO_FOTO = dict(MOMENTOS_FOTO)


def preparar_foto(datos):
    """Bytes subidos → (jpeg, miniatura, ancho, alto).

    Gira la foto según la cámara y le quita los metadatos (ubicación GPS,
    modelo del celular). Lo que no sea imagen se rechaza aunque traiga
    extensión de imagen."""
    from io import BytesIO

    from PIL import Image, ImageOps, UnidentifiedImageError
    if not datos:
        raise ErrorServicio('La foto llegó vacía.')
    if len(datos) > FOTO_MAX_BYTES:
        raise ErrorServicio('La foto pesa más de 15 MB.')
    try:
        img = Image.open(BytesIO(datos))
        formato = img.format
        img.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ErrorServicio('El archivo no es una imagen válida (usa JPG, PNG o WEBP).')
    if formato not in ('JPEG', 'MPO', 'PNG', 'WEBP', 'GIF', 'BMP'):
        raise ErrorServicio('Formato de imagen no admitido (usa JPG, PNG o WEBP).')
    img = ImageOps.exif_transpose(img)
    if img.mode in ('RGBA', 'LA', 'P'):
        img = img.convert('RGBA')
        fondo = Image.new('RGB', img.size, (255, 255, 255))
        fondo.paste(img, mask=img.split()[-1])
        img = fondo
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    def _jpeg(lado, calidad):
        copia = img.copy()
        copia.thumbnail((lado, lado), Image.LANCZOS)
        salida = BytesIO()
        copia.save(salida, 'JPEG', quality=calidad, optimize=True, progressive=True)
        return salida.getvalue(), copia.size

    grande, (ancho, alto) = _jpeg(FOTO_LADO, 82)
    mini, _ = _jpeg(MINI_LADO, 72)
    return grande, mini, ancho, alto


def guardar_fotos(equipo_id, archivos, momento='ficha', descripcion=None, usuario_id=None, orden_id=None):
    """Guarda las fotos que se puedan. Devuelve (guardadas, errores)."""
    if momento not in MOMENTO_FOTO:
        momento = 'ficha'
    descripcion = _texto(descripcion, 200)
    archivos = [a for a in (archivos or []) if a and getattr(a, 'filename', '')]
    if not archivos:
        return 0, []
    guardadas, errores = 0, []
    with get_db_cursor() as cur:
        cur.execute('SELECT id FROM st_equipos WHERE id = %s FOR UPDATE', (equipo_id,))
        if not cur.fetchone():
            raise ErrorServicio('El equipo no existe.')
        if orden_id:
            cur.execute('SELECT 1 FROM st_ordenes WHERE id = %s AND equipo_id = %s', (orden_id, equipo_id))
            if not cur.fetchone():
                orden_id = None
        cur.execute('SELECT COUNT(*) FROM st_fotos WHERE equipo_id = %s AND activo', (equipo_id,))
        cupo = FOTOS_MAX - int(cur.fetchone()[0])
        for archivo in archivos:
            nombre = (archivo.filename or 'foto')[:60]
            if cupo <= 0:
                errores.append(f'{nombre}: el equipo ya tiene {FOTOS_MAX} fotos. Quita alguna para subir más.')
                continue
            try:
                grande, mini, ancho, alto = preparar_foto(archivo.read(FOTO_MAX_BYTES + 1))
            except ErrorServicio as exc:
                errores.append(f'{nombre}: {exc}')
                continue
            cur.execute("""INSERT INTO st_fotos (equipo_id, orden_id, momento, descripcion, mime, ancho, alto,
                                                 bytes, contenido, miniatura, creado_por)
                           VALUES (%s, %s, %s, %s, 'image/jpeg', %s, %s, %s, %s, %s, %s)""",
                        (equipo_id, orden_id, momento, descripcion, ancho, alto, len(grande),
                         grande, mini, usuario_id))
            guardadas += 1
            cupo -= 1
        if guardadas:
            _evento(cur, orden_id, equipo_id, 'foto',
                    f"{guardadas} foto{'s' if guardadas != 1 else ''} agregada{'s' if guardadas != 1 else ''} "
                    f"({MOMENTO_FOTO[momento].lower()})", usuario_id)
            cur.execute('UPDATE st_equipos SET actualizado_en = NOW() WHERE id = %s', (equipo_id,))
    return guardadas, errores


def fotos_de_equipo(equipo_id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT f.id, f.orden_id, f.momento, f.descripcion, f.ancho, f.alto, f.bytes, f.creado_en,
                              o.numero AS orden_numero
                       FROM st_fotos f LEFT JOIN st_ordenes o ON o.id = f.orden_id
                       WHERE f.equipo_id = %s AND f.activo ORDER BY f.creado_en DESC, f.id DESC""",
                    (equipo_id,))
        return [dict(r) for r in cur.fetchall()]


def foto_contenido(foto_id, miniatura=False):
    """(mime, bytes) de una foto activa, o None."""
    columna = 'miniatura' if miniatura else 'contenido'
    with get_db_cursor() as cur:
        cur.execute(f'SELECT mime, {columna} FROM st_fotos WHERE id = %s AND activo', (foto_id,))
        fila = cur.fetchone()
    return (fila[0], bytes(fila[1])) if fila else None


def quitar_foto(foto_id, usuario_id=None):
    """Retira la foto de la ficha (queda guardada, no se borra). Devuelve el
    id del equipo o None."""
    with get_db_cursor() as cur:
        cur.execute('UPDATE st_fotos SET activo = FALSE WHERE id = %s AND activo RETURNING equipo_id, orden_id',
                    (foto_id,))
        fila = cur.fetchone()
        if not fila:
            return None
        _evento(cur, fila[1], fila[0], 'foto', 'Foto retirada de la ficha', usuario_id)
    return fila[0]


# ── Mantenimientos preventivos y correctivos ────────────────────
TIPOS_MANTENIMIENTO = [
    ('preventivo', 'Preventivo', 'shield-alt'),
    ('correctivo', 'Correctivo', 'wrench'),
]
TIPO_MANTENIMIENTO = {t[0]: t for t in TIPOS_MANTENIMIENTO}


def guardar_plan_mantenimiento(equipo_id, cada_meses, proximo=None, usuario_id=None):
    """Cada cuántos meses se le hace mantenimiento preventivo y cuándo toca el
    próximo. Reemplaza el recordatorio de mantenimiento pendiente del equipo."""
    meses = _cada_meses(cada_meses)
    proximo = _fecha(proximo)
    hoy = date.today()
    if proximo and proximo < hoy:
        raise ErrorServicio('La fecha del próximo mantenimiento ya pasó.')
    from services import servicio_tecnico_seguimiento as seg
    if meses and not proximo:
        proximo = seg._sumar_meses(hoy, meses)
    with get_db_cursor() as cur:
        cur.execute('SELECT crm_contacto_id FROM st_equipos WHERE id = %s FOR UPDATE', (equipo_id,))
        fila = cur.fetchone()
        if not fila:
            raise ErrorServicio('El equipo no existe.')
        cur.execute('UPDATE st_equipos SET mant_cada_meses = %s, mant_proximo = %s, actualizado_en = NOW() '
                    'WHERE id = %s', (meses or None, proximo, equipo_id))
        if proximo:
            seg.cerrar_de_equipo(cur, equipo_id, ['mantenimiento'], 'Reemplazado por el plan del equipo')
            seg.programar(cur, 'mantenimiento', proximo, equipo_id=equipo_id, contacto_id=fila[0])
            detalle = (f'Plan de mantenimiento: cada {meses} meses, próximo el {proximo.strftime("%d/%m/%Y")}'
                       if meses else f'Mantenimiento programado para el {proximo.strftime("%d/%m/%Y")}')
        else:
            seg.cerrar_de_equipo(cur, equipo_id, ['mantenimiento'], 'Plan de mantenimiento retirado',
                                 solo_sin_orden=True)
            detalle = 'Plan de mantenimiento retirado'
        _evento(cur, None, equipo_id, 'equipo', detalle, usuario_id)
    return proximo


def registrar_mantenimiento(equipo_id, datos, usuario_id=None):
    """Registra un mantenimiento hecho. El preventivo cierra el recordatorio
    pendiente y programa el siguiente (fecha dada o según el plan)."""
    tipo = (datos.get('tipo') or '').strip()
    if tipo not in TIPO_MANTENIMIENTO:
        raise ErrorServicio('Escoge si el mantenimiento fue preventivo o correctivo.')
    descripcion = _texto(datos.get('descripcion'), 4000)
    if not descripcion:
        raise ErrorServicio('Describe qué se le hizo al equipo.')
    hoy = date.today()
    fecha = _fecha(datos.get('fecha')) or hoy
    if fecha > hoy:
        raise ErrorServicio('La fecha del mantenimiento no puede ser futura: para programarlo usa el plan o un recordatorio.')
    proxima = _fecha(datos.get('proxima_fecha'))
    if proxima and proxima <= fecha:
        raise ErrorServicio('El próximo mantenimiento debe ser posterior a este.')
    costo = _numero(datos.get('costo'))
    try:
        tecnico_id = int(datos.get('tecnico_id')) if datos.get('tecnico_id') else None
        orden_id = int(datos.get('orden_id')) if datos.get('orden_id') else None
    except (TypeError, ValueError):
        raise ErrorServicio('Datos del mantenimiento no válidos.')
    from services import servicio_tecnico_seguimiento as seg
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute('SELECT id, crm_contacto_id, mant_cada_meses FROM st_equipos WHERE id = %s FOR UPDATE',
                    (equipo_id,))
        equipo = cur.fetchone()
        if not equipo:
            raise ErrorServicio('El equipo no existe.')
        if orden_id:
            cur.execute('SELECT 1 FROM st_ordenes WHERE id = %s AND equipo_id = %s', (orden_id, equipo_id))
            if not cur.fetchone():
                raise ErrorServicio('La orden escogida no es de este equipo.')
        if not proxima and tipo == 'preventivo' and equipo['mant_cada_meses']:
            proxima = seg._sumar_meses(fecha, int(equipo['mant_cada_meses']))
            if proxima <= hoy:
                proxima = seg._sumar_meses(hoy, int(equipo['mant_cada_meses']))
        cur.execute("""INSERT INTO st_mantenimientos (equipo_id, orden_id, tipo, fecha, descripcion, hallazgos,
                                                      tecnico_id, costo, proxima_fecha, creado_por)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                    (equipo_id, orden_id, tipo, fecha, descripcion, _texto(datos.get('hallazgos'), 4000),
                     tecnico_id, costo, proxima, usuario_id))
        mant_id = cur.fetchone()['id']
        if tipo == 'preventivo':
            seg.cerrar_de_equipo(cur, equipo_id, ['mantenimiento'], 'Mantenimiento hecho', estado='hecho')
        if proxima:
            seg.cerrar_de_equipo(cur, equipo_id, ['mantenimiento'], 'Reprogramado')
            seg.programar(cur, 'mantenimiento', proxima, equipo_id=equipo_id,
                          contacto_id=equipo['crm_contacto_id'])
            cur.execute('UPDATE st_equipos SET mant_proximo = %s WHERE id = %s', (proxima, equipo_id))
        elif tipo == 'preventivo':
            cur.execute('UPDATE st_equipos SET mant_proximo = NULL WHERE id = %s', (equipo_id,))
        cur.execute('UPDATE st_equipos SET actualizado_en = NOW() WHERE id = %s', (equipo_id,))
        nombre = TIPO_MANTENIMIENTO[tipo][1]
        _evento(cur, orden_id, equipo_id, 'mantenimiento', f'Mantenimiento {nombre.lower()}: {descripcion[:160]}',
                usuario_id)
        _actividad_crm(cur, equipo['crm_contacto_id'], 'nota', f'Servicio técnico: mantenimiento {nombre.lower()}',
                       descripcion[:500], usuario_id)
    return mant_id


def hoja_de_vida(mantenimientos, ordenes, cambios=()):
    """Servicios del taller, mantenimientos y piezas cambiadas en una sola
    línea de tiempo (lo más reciente primero)."""
    filas = []
    for c in cambios:
        filas.append({'fecha': c['fecha'], 'clase': 'pieza', 'titulo': f"Pieza cambiada: {c['componente']}",
                      'detalle': c.get('detalle'), 'proxima': c.get('proxima_revision'),
                      'orden_id': c.get('orden_id'), 'orden_numero': c.get('orden_numero')})
    for m in mantenimientos:
        filas.append({'fecha': m['fecha'], 'clase': m['tipo'],
                      'titulo': f"Mantenimiento {TIPO_MANTENIMIENTO.get(m['tipo'], (m['tipo'], m['tipo']))[1].lower()}",
                      'detalle': m['descripcion'], 'hallazgos': m.get('hallazgos'),
                      'tecnico': m.get('tecnico_nombre'), 'costo': m.get('costo'),
                      'proxima': m.get('proxima_fecha'), 'orden_id': m.get('orden_id'),
                      'orden_numero': m.get('orden_numero')})
    for o in ordenes:
        recibido = o['fecha_recibido']
        filas.append({'fecha': recibido.date() if hasattr(recibido, 'date') else recibido, 'clase': 'orden',
                      'titulo': f"Servicio {o['numero']}", 'detalle': o.get('falla_reportada'),
                      'solucion': o.get('solucion') or o.get('resumen_caso'), 'estado': o.get('estado'),
                      'costo': o.get('valor_final'), 'orden_id': o['id'], 'orden_numero': o['numero']})
    filas.sort(key=lambda f: f['fecha'], reverse=True)
    return filas


def mantenimientos_de_equipo(equipo_id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT m.*, u.nombre AS tecnico_nombre, o.numero AS orden_numero
                       FROM st_mantenimientos m
                       LEFT JOIN usuarios u ON u.id = m.tecnico_id
                       LEFT JOIN st_ordenes o ON o.id = m.orden_id
                       WHERE m.equipo_id = %s AND m.activo ORDER BY m.fecha DESC, m.id DESC""", (equipo_id,))
        return [dict(r) for r in cur.fetchall()]


# ── Validación de la ficha ──────────────────────────────────────
def validacion_equipo(equipo, fotos=0, recordatorios=0):
    """¿Está completa la ficha? Lista de revisiones (estado, texto, ir):
    estado ok | aviso | error; `ir` dice dónde se arregla (editar, fotos,
    datos, crm, mantenimiento o None). Solo reglas fijas: no usa IA.
    Devuelve {'puntaje', 'revisiones', 'faltan', 'errores'}."""
    revisiones = []
    columnas = tipos.columnas(equipo['tipo'])
    extras = equipo.get('extras') or {}

    faltan_mm = [tipos.ETIQUETAS_COMUNES[c].lower() for c in ('marca', 'modelo') if not equipo.get(c)]
    revisiones.append(('aviso', 'Falta ' + ' y '.join('la ' + f for f in faltan_mm), 'editar') if faltan_mm
                      else ('ok', 'Marca y modelo', None))

    if 'imei' in columnas:
        if not equipo.get('imei'):
            revisiones.append(('aviso', 'Falta el IMEI (márcalo con *#06# en el equipo)', 'editar'))
        elif imei_valido(equipo['imei']):
            revisiones.append(('ok', 'IMEI correcto', None))
        else:
            revisiones.append(('error', 'El IMEI está mal escrito: revísalo', 'editar'))
    if equipo.get('serial'):
        with get_db_cursor() as cur:
            cur.execute("""SELECT COUNT(*) FROM st_equipos WHERE activo AND id <> %s AND lower(serial) = lower(%s)""",
                        (equipo['id'], equipo['serial']))
            otros = int(cur.fetchone()[0])
        revisiones.append(('aviso', 'Ese serial también está en otro equipo: confírmalo', 'editar')
                          if otros else ('ok', 'Serial', None))
    else:
        revisiones.append(('aviso', 'Falta el serial (está en la etiqueta del equipo)', 'editar'))

    claves = list(columnas) + tipos.claves_extra(equipo['tipo'])
    llenos = sum(1 for c in columnas if equipo.get(c)) + sum(1 for c in tipos.claves_extra(equipo['tipo']) if extras.get(c))
    porcentaje = round(100 * llenos / len(claves)) if claves else 100
    sin_llenar = len(claves) - llenos
    revisiones.append(('ok', 'Datos técnicos', None) if porcentaje >= 70
                      else ('aviso', f'Faltan {sin_llenar} datos técnicos: pégalos desde la información del equipo', 'datos'))

    revisiones.append(('ok', f'{fotos} foto(s)', None) if fotos
                      else ('aviso', 'No tiene fotos del equipo', 'fotos'))
    if equipo.get('cliente_whatsapp') or equipo.get('cliente_telefono') or equipo.get('cliente_email'):
        revisiones.append(('ok', 'Contacto del cliente', None))
    else:
        revisiones.append(('aviso', 'El cliente no tiene WhatsApp ni correo para avisarle', 'crm'))
    if equipo.get('mant_proximo'):
        revisiones.append(('ok', f"Mantenimiento programado: {equipo['mant_proximo'].strftime('%d/%m/%Y')}", None))
    elif recordatorios:
        revisiones.append(('ok', f'{recordatorios} recordatorio(s) pendiente(s)', None))
    else:
        revisiones.append(('aviso', 'No tiene mantenimiento ni recordatorios programados', 'mantenimiento'))

    puntos = sum(1 for r in revisiones if r[0] == 'ok')
    return {'puntaje': round(100 * puntos / len(revisiones)), 'revisiones': revisiones,
            'faltan': [r for r in revisiones if r[0] != 'ok'],
            'errores': sum(1 for r in revisiones if r[0] == 'error')}


# ── Documentos del equipo (PDF, Excel, Word…) ───────────────────
DOCUMENTO_MAX_BYTES = 20 * 1024 * 1024
DOCUMENTOS_MAX = 40                     # documentos activos por equipo
# extensión → (mime, firma con la que empieza el archivo; None = texto)
TIPOS_DOCUMENTO = {
    'pdf': ('application/pdf', b'%PDF-'),
    'xlsx': ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', b'PK\x03\x04'),
    'xlsm': ('application/vnd.ms-excel.sheet.macroEnabled.12', b'PK\x03\x04'),
    'xls': ('application/vnd.ms-excel', b'\xd0\xcf\x11\xe0'),
    'docx': ('application/vnd.openxmlformats-officedocument.wordprocessingml.document', b'PK\x03\x04'),
    'doc': ('application/msword', b'\xd0\xcf\x11\xe0'),
    'ods': ('application/vnd.oasis.opendocument.spreadsheet', b'PK\x03\x04'),
    'odt': ('application/vnd.oasis.opendocument.text', b'PK\x03\x04'),
    'csv': ('text/csv', None),
    'txt': ('text/plain', None),
}
ACEPTA_DOCUMENTOS = ','.join('.' + e for e in TIPOS_DOCUMENTO)


def nombre_archivo(nombre):
    """Nombre para mostrar y descargar: sin carpetas ni caracteres raros."""
    nombre = os.path.basename(str(nombre or '').replace('\\', '/')).strip()
    nombre = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', '_', nombre)
    return (nombre or 'documento')[:200]


def validar_documento(nombre, datos):
    """(nombre, extensión, mime) si el archivo es de un tipo admitido y su
    contenido corresponde a la extensión; si no, ErrorServicio."""
    nombre = nombre_archivo(nombre)
    ext = nombre.rsplit('.', 1)[-1].lower() if '.' in nombre else ''
    if ext not in TIPOS_DOCUMENTO:
        raise ErrorServicio(f'{nombre}: tipo de archivo no admitido (usa PDF, Excel, Word, CSV o texto).')
    if not datos:
        raise ErrorServicio(f'{nombre}: el archivo llegó vacío.')
    if len(datos) > DOCUMENTO_MAX_BYTES:
        raise ErrorServicio(f'{nombre}: pesa más de 20 MB.')
    mime, firma = TIPOS_DOCUMENTO[ext]
    if firma and not datos.startswith(firma):
        raise ErrorServicio(f'{nombre}: el contenido no corresponde a un archivo .{ext}.')
    if firma is None and b'\x00' in datos[:4096]:
        raise ErrorServicio(f'{nombre}: no es un archivo de texto.')
    return nombre, ext, mime


def guardar_documento(cur, nombre, mime, datos, texto=None, equipo_id=None, importacion_id=None,
                      usuario_id=None, descripcion=None, orden_id=None):
    """Guarda el archivo en la base del cliente. Devuelve su id."""
    cur.execute("""INSERT INTO st_documentos (equipo_id, orden_id, importacion_id, nombre, descripcion, mime, bytes,
                                              huella, contenido, texto, creado_por)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (equipo_id, orden_id, importacion_id, nombre_archivo(nombre), _texto(descripcion, 200), mime,
                 len(datos), hashlib.sha256(datos).hexdigest(), datos, (texto or '')[:200000] or None, usuario_id))
    return cur.fetchone()[0]


def adjuntar_documentos(equipo_id, archivos, descripcion=None, usuario_id=None):
    """Documentos subidos desde la ficha. Guarda los que se puedan y devuelve
    (guardados, errores)."""
    archivos = [a for a in (archivos or []) if a and getattr(a, 'filename', '')]
    if not archivos:
        return 0, []
    guardados, errores = 0, []
    with get_db_cursor() as cur:
        cur.execute('SELECT id FROM st_equipos WHERE id = %s FOR UPDATE', (equipo_id,))
        if not cur.fetchone():
            raise ErrorServicio('El equipo no existe.')
        cur.execute('SELECT COUNT(*) FROM st_documentos WHERE equipo_id = %s AND activo', (equipo_id,))
        cupo = DOCUMENTOS_MAX - int(cur.fetchone()[0])
        for archivo in archivos:
            nombre = nombre_archivo(archivo.filename)
            if cupo <= 0:
                errores.append(f'{nombre}: el equipo ya tiene {DOCUMENTOS_MAX} documentos. Quita alguno para subir más.')
                continue
            datos = archivo.read(DOCUMENTO_MAX_BYTES + 1)
            try:
                nombre, _ext, mime = validar_documento(nombre, datos)
            except ErrorServicio as exc:
                errores.append(str(exc))
                continue
            guardar_documento(cur, nombre, mime, datos, equipo_id=equipo_id, usuario_id=usuario_id,
                              descripcion=descripcion)
            guardados += 1
            cupo -= 1
        if guardados:
            _evento(cur, None, equipo_id, 'documento',
                    f"{guardados} documento{'s' if guardados != 1 else ''} agregado{'s' if guardados != 1 else ''}",
                    usuario_id)
            cur.execute('UPDATE st_equipos SET actualizado_en = NOW() WHERE id = %s', (equipo_id,))
    return guardados, errores


def documentos_de_equipo(equipo_id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT id, nombre, descripcion, mime, bytes, creado_en, importacion_id
                       FROM st_documentos WHERE equipo_id = %s AND activo
                       ORDER BY creado_en DESC, id DESC""", (equipo_id,))
        return [dict(r) for r in cur.fetchall()]


def documento_contenido(doc_id):
    """(mime, nombre, bytes) de un documento activo, o None."""
    with get_db_cursor() as cur:
        cur.execute('SELECT mime, nombre, contenido FROM st_documentos WHERE id = %s AND activo', (doc_id,))
        fila = cur.fetchone()
    return (fila[0], fila[1], bytes(fila[2])) if fila else None


def quitar_documento(doc_id, usuario_id=None):
    """Retira el documento de la ficha (queda guardado, no se borra). Devuelve
    el id del equipo o None."""
    with get_db_cursor() as cur:
        cur.execute("""UPDATE st_documentos SET activo = FALSE
                       WHERE id = %s AND activo AND equipo_id IS NOT NULL RETURNING equipo_id, nombre""", (doc_id,))
        fila = cur.fetchone()
        if not fila:
            return None
        _evento(cur, None, fila[0], 'documento', f'Documento retirado de la ficha: {fila[1]}', usuario_id)
    return fila[0]
