"""
routes/share.py - Modulo "Compartir Archivos".

Permite que un admin cree carpetas (con subcarpetas anidadas), suba archivos
y comparta un link publico (token + clave opcional) para que sus clientes
descarguen documentos. Opcionalmente el cliente puede subir archivos.

Rutas admin: CRUD de carpetas y archivos bajo /admin/compartir.
Rutas publicas: navegacion del cliente bajo /c/<token>.
"""

import os
import secrets
import shutil
import json
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session,
    send_from_directory, abort, current_app as app
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

from database import get_db_cursor
from helpers import get_data_app
from security import rol_requerido, ADMIN_STAFF
from tenant_features import module_required, MODULE_SHARE


share_bp = Blueprint('share', __name__)


ALLOWED_EXTENSIONS = {
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'png', 'jpg', 'jpeg', 'gif',
    'zip', 'rar', 'txt', 'csv',
}

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB por archivo


# ─────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────

def _upload_root():
    # Mantener almacenamiento fuera de /static evita bypass del token por URL directa.
    folder = os.path.join(app.root_path, 'uploads', 'share')
    os.makedirs(folder, exist_ok=True)
    return folder


def _legacy_upload_root():
    return os.path.join(app.root_path, 'static', 'uploads', 'share')


def _carpeta_dir(carpeta_raiz_id, create=True, legacy=False):
    base_dir = _legacy_upload_root() if legacy else _upload_root()
    folder = os.path.join(base_dir, str(carpeta_raiz_id))
    if create:
        os.makedirs(folder, exist_ok=True)
    return folder


def _resolver_archivo_path(carpeta_raiz_id, nombre_almacenado):
    for legacy in (False, True):
        folder = _carpeta_dir(carpeta_raiz_id, create=False, legacy=legacy)
        file_path = os.path.join(folder, nombre_almacenado)
        if os.path.isfile(file_path):
            return file_path
    return os.path.join(_carpeta_dir(carpeta_raiz_id, create=False), nombre_almacenado)


def _generar_token():
    return secrets.token_urlsafe(24)


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _get_carpeta(carpeta_id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM share_carpetas WHERE id = %s", (carpeta_id,))
        return cur.fetchone()


def _get_carpeta_por_token(token):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM share_carpetas WHERE token = %s AND parent_id IS NULL", (token,))
        return cur.fetchone()


def _crear_subcarpeta_si_no_existe(parent_id, nombre):
    nombre = (nombre or '').strip()[:200]
    if not nombre:
        return None, False

    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT id
            FROM share_carpetas
            WHERE parent_id = %s AND nombre = %s
            ORDER BY id
            LIMIT 1
        """, (parent_id, nombre))
        existente = cur.fetchone()
        if existente:
            return existente['id'], False

        cur.execute("""
            INSERT INTO share_carpetas (parent_id, nombre, creado_por)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (parent_id, nombre, session.get('usuario_id')))
        creada = cur.fetchone()
        return creada['id'], True


def _carpeta_raiz_id(carpeta_id):
    """Sube por parent_id hasta llegar a la raiz. Devuelve el id de la raiz o None."""
    actual_id = carpeta_id
    visitados = set()
    with get_db_cursor(dict_cursor=True) as cur:
        while actual_id is not None and actual_id not in visitados:
            visitados.add(actual_id)
            cur.execute("SELECT id, parent_id FROM share_carpetas WHERE id = %s", (actual_id,))
            row = cur.fetchone()
            if not row:
                return None
            if row['parent_id'] is None:
                return row['id']
            actual_id = row['parent_id']
    return None


def _es_descendiente(carpeta_id, raiz_id):
    """True si carpeta_id == raiz_id o si raiz_id es ancestro."""
    if carpeta_id == raiz_id:
        return True
    return _carpeta_raiz_id(carpeta_id) == raiz_id


def _breadcrumbs(carpeta_id):
    """Lista [{id, nombre}] desde la raiz hasta la carpeta actual."""
    crumbs = []
    actual_id = carpeta_id
    visitados = set()
    with get_db_cursor(dict_cursor=True) as cur:
        while actual_id is not None and actual_id not in visitados:
            visitados.add(actual_id)
            cur.execute("SELECT id, parent_id, nombre FROM share_carpetas WHERE id = %s", (actual_id,))
            row = cur.fetchone()
            if not row:
                break
            crumbs.append({'id': row['id'], 'nombre': row['nombre']})
            actual_id = row['parent_id']
    crumbs.reverse()
    return crumbs


def _parsear_ruta_importada(ruta_relativa, fallback_filename):
    ruta = (ruta_relativa or '').replace('\\', '/').strip()
    nombre_fallback = os.path.basename((fallback_filename or '').replace('\\', '/')).strip()

    if not ruta:
        return [], nombre_fallback

    ruta = ruta.lstrip('/')
    partes = [p.strip() for p in ruta.split('/') if p.strip()]
    if not partes or any(p in {'.', '..'} for p in partes):
        return None, None

    nombre_archivo = partes[-1][:255]
    subcarpetas = [p[:200] for p in partes[:-1]]
    return subcarpetas, nombre_archivo


def _resolver_carpeta_destino_importacion(carpeta_base_id, subcarpetas):
    destino_id = carpeta_base_id
    creadas = 0
    for nombre in subcarpetas:
        destino_id, fue_creada = _crear_subcarpeta_si_no_existe(destino_id, nombre)
        if not destino_id:
            return None, creadas
        if fue_creada:
            creadas += 1
    return destino_id, creadas


def _registrar_acceso(carpeta_raiz_id, archivo_id, accion):
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                INSERT INTO share_accesos (carpeta_raiz_id, archivo_id, accion, ip, user_agent)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                carpeta_raiz_id, archivo_id, accion,
                request.remote_addr,
                (request.user_agent.string or '')[:500]
            ))
    except Exception as e:
        app.logger.warning(f"No se pudo registrar acceso share: {e}")


def _esta_vencida(carpeta_raiz):
    if not carpeta_raiz.get('fecha_vence'):
        return False
    return datetime.now() > carpeta_raiz['fecha_vence']


def _clave_validada(carpeta_raiz):
    token = carpeta_raiz.get('token')
    clave_hash = carpeta_raiz.get('clave_hash')
    if not token or not clave_hash:
        return False
    return session.get(f'share_ok_{token}') == clave_hash


def _carpeta_resumen(carpeta_id):
    """Devuelve totales (archivos, bytes) de una carpeta y todas sus descendientes."""
    sql = """
        WITH RECURSIVE arbol AS (
            SELECT id FROM share_carpetas WHERE id = %s
            UNION ALL
            SELECT c.id FROM share_carpetas c JOIN arbol a ON c.parent_id = a.id
        )
        SELECT COUNT(a.id) AS total_archivos, COALESCE(SUM(a.tamano_bytes), 0) AS total_bytes
        FROM share_archivos a
        WHERE a.carpeta_id IN (SELECT id FROM arbol)
    """
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(sql, (carpeta_id,))
        row = cur.fetchone()
        return {
            'total_archivos': row['total_archivos'] if row else 0,
            'total_bytes': int(row['total_bytes']) if row and row['total_bytes'] else 0,
        }


def _format_bytes(n):
    if n is None:
        return '0 B'
    n = int(n)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != 'B' else f"{n} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _eliminar_carpeta_disco(carpeta_raiz_id):
    """Borra la carpeta fisica de la raiz (incluye compatibilidad legacy)."""
    for legacy in (False, True):
        folder = _carpeta_dir(carpeta_raiz_id, create=False, legacy=legacy)
        if os.path.isdir(folder):
            try:
                shutil.rmtree(folder)
            except Exception as e:
                app.logger.warning(f"No se pudo borrar carpeta fisica {folder}: {e}")


def _listar_archivos_subarbol(carpeta_id):
    sql = """
        WITH RECURSIVE arbol AS (
            SELECT id FROM share_carpetas WHERE id = %s
            UNION ALL
            SELECT c.id FROM share_carpetas c JOIN arbol a ON c.parent_id = a.id
        )
        SELECT id, nombre_almacenado
        FROM share_archivos
        WHERE carpeta_id IN (SELECT id FROM arbol)
    """
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(sql, (carpeta_id,))
        return [dict(row) for row in cur.fetchall()]


def _eliminar_archivos_fisicos(raiz_id, archivos):
    for archivo in archivos:
        file_path = _resolver_archivo_path(raiz_id, archivo['nombre_almacenado'])
        if os.path.isfile(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                app.logger.warning(f"No se pudo borrar archivo fisico {file_path}: {e}")


def _icono_archivo(nombre):
    ext = nombre.rsplit('.', 1)[-1].lower() if '.' in nombre else ''
    mapa = {
        'pdf': 'file-pdf', 'doc': 'file-word', 'docx': 'file-word',
        'xls': 'file-excel', 'xlsx': 'file-excel', 'csv': 'file-csv',
        'ppt': 'file-powerpoint', 'pptx': 'file-powerpoint',
        'png': 'file-image', 'jpg': 'file-image', 'jpeg': 'file-image',
        'gif': 'file-image', 'webp': 'file-image', 'svg': 'file-image',
        'zip': 'file-archive', 'rar': 'file-archive', '7z': 'file-archive',
        'tar': 'file-archive', 'gz': 'file-archive',
        'mp3': 'file-audio', 'wav': 'file-audio',
        'mp4': 'file-video', 'mov': 'file-video', 'avi': 'file-video',
        'txt': 'file-alt',
    }
    return mapa.get(ext, 'file')


# ─────────────────────────────────────────────────────────
# Rutas ADMIN
# ─────────────────────────────────────────────────────────

@share_bp.route('/admin/compartir')
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SHARE)
def gestion_carpetas():
    """Lista las carpetas raiz con su token, vencimiento y totales."""
    datosApp = get_data_app()
    carpetas = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT * FROM share_carpetas
                WHERE parent_id IS NULL
                ORDER BY fecha_creacion DESC
            """)
            carpetas = [dict(row) for row in cur.fetchall()]

        for c in carpetas:
            resumen = _carpeta_resumen(c['id'])
            c['total_archivos'] = resumen['total_archivos']
            c['total_bytes_fmt'] = _format_bytes(resumen['total_bytes'])
            c['link_publico'] = url_for('share.publico_raiz', token=c['token'], _external=True) if c['token'] else None
            c['vencida'] = _esta_vencida(c)
    except Exception as e:
        app.logger.error(f"Error listando carpetas share: {e}")

    return render_template('share/admin_lista.html', datosApp=datosApp, carpetas=carpetas)


@share_bp.route('/admin/compartir/crear', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SHARE)
def crear_carpeta():
    """Crea una carpeta raiz con token y opcionalmente clave/vencimiento."""
    datosApp = get_data_app()
    if request.method == 'POST':
        nombre = (request.form.get('nombre') or '').strip()
        descripcion = (request.form.get('descripcion') or '').strip() or None
        clave = (request.form.get('clave') or '').strip() or None
        permitir_subida = request.form.get('permitir_subida') == 'on'
        fecha_vence_raw = (request.form.get('fecha_vence') or '').strip() or None

        if not nombre:
            flash('El nombre de la carpeta es obligatorio.', 'error')
            return render_template('share/admin_carpeta_form.html',
                                   datosApp=datosApp, carpeta=None, modo='crear')

        clave_hash = generate_password_hash(clave) if clave else None
        fecha_vence = None
        if fecha_vence_raw:
            try:
                fecha_vence = datetime.fromisoformat(fecha_vence_raw)
            except ValueError:
                flash('Fecha de vencimiento invalida.', 'error')
                return render_template('share/admin_carpeta_form.html',
                                       datosApp=datosApp, carpeta=None, modo='crear')

        token = _generar_token()
        try:
            with get_db_cursor(dict_cursor=True) as cur:
                cur.execute("""
                    INSERT INTO share_carpetas
                        (parent_id, nombre, descripcion, token, clave_hash,
                         permitir_subida, fecha_vence, creado_por)
                    VALUES (NULL, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (nombre, descripcion, token, clave_hash,
                      permitir_subida, fecha_vence, session.get('usuario_id')))
                nueva_id = cur.fetchone()['id']
            flash(f'Carpeta "{nombre}" creada. Comparte el link con tu cliente.', 'success')
            return redirect(url_for('share.ver_carpeta_admin', carpeta_id=nueva_id))
        except Exception as e:
            app.logger.error(f"Error creando carpeta share: {e}")
            flash('No se pudo crear la carpeta.', 'error')

    return render_template('share/admin_carpeta_form.html',
                           datosApp=datosApp, carpeta=None, modo='crear')


@share_bp.route('/admin/compartir/carpeta/<int:carpeta_id>')
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SHARE)
def ver_carpeta_admin(carpeta_id):
    """Vista de una carpeta: subcarpetas, archivos y opciones."""
    datosApp = get_data_app()
    carpeta = _get_carpeta(carpeta_id)
    if not carpeta:
        flash('Carpeta no encontrada.', 'error')
        return redirect(url_for('share.gestion_carpetas'))

    raiz_id = _carpeta_raiz_id(carpeta_id)
    raiz = _get_carpeta(raiz_id) if raiz_id else None

    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT id, nombre, fecha_creacion
            FROM share_carpetas
            WHERE parent_id = %s
            ORDER BY nombre
        """, (carpeta_id,))
        subcarpetas = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT * FROM share_archivos
            WHERE carpeta_id = %s
            ORDER BY fecha_subida DESC
        """, (carpeta_id,))
        archivos = []
        for row in cur.fetchall():
            d = dict(row)
            d['tamano_fmt'] = _format_bytes(d.get('tamano_bytes'))
            d['icono'] = _icono_archivo(d['nombre_original'])
            archivos.append(d)

    crumbs = _breadcrumbs(carpeta_id)
    es_raiz = carpeta['parent_id'] is None
    link_publico = url_for('share.publico_raiz', token=raiz['token'], _external=True) if raiz and raiz['token'] else None

    return render_template(
        'share/admin_carpeta.html',
        datosApp=datosApp,
        carpeta=carpeta,
        carpeta_raiz=raiz,
        es_raiz=es_raiz,
        breadcrumbs=crumbs,
        subcarpetas=subcarpetas,
        archivos=archivos,
        link_publico=link_publico,
    )


@share_bp.route('/admin/compartir/carpeta/<int:carpeta_id>/editar', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SHARE)
def editar_carpeta(carpeta_id):
    datosApp = get_data_app()
    carpeta = _get_carpeta(carpeta_id)
    if not carpeta:
        flash('Carpeta no encontrada.', 'error')
        return redirect(url_for('share.gestion_carpetas'))

    es_raiz = carpeta['parent_id'] is None

    if request.method == 'POST':
        nombre = (request.form.get('nombre') or '').strip()
        descripcion = (request.form.get('descripcion') or '').strip() or None
        permitir_subida = request.form.get('permitir_subida') == 'on'

        if not nombre:
            flash('El nombre es obligatorio.', 'error')
            return render_template('share/admin_carpeta_form.html',
                                   datosApp=datosApp, carpeta=carpeta, modo='editar')

        clave_raw = (request.form.get('clave') or '').strip()
        quitar_clave = request.form.get('quitar_clave') == 'on'
        fecha_vence_raw = (request.form.get('fecha_vence') or '').strip()

        clave_hash = carpeta['clave_hash']
        fecha_vence = carpeta['fecha_vence']

        if es_raiz:
            if quitar_clave:
                clave_hash = None
            elif clave_raw:
                clave_hash = generate_password_hash(clave_raw)

            if fecha_vence_raw:
                try:
                    fecha_vence = datetime.fromisoformat(fecha_vence_raw)
                except ValueError:
                    flash('Fecha de vencimiento invalida.', 'error')
                    return render_template('share/admin_carpeta_form.html',
                                           datosApp=datosApp, carpeta=carpeta, modo='editar')
            else:
                fecha_vence = None

        try:
            with get_db_cursor() as cur:
                cur.execute("""
                    UPDATE share_carpetas SET
                        nombre = %s,
                        descripcion = %s,
                        permitir_subida = %s,
                        clave_hash = %s,
                        fecha_vence = %s,
                        fecha_actualizacion = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (nombre, descripcion, permitir_subida, clave_hash, fecha_vence, carpeta_id))
            flash('Carpeta actualizada.', 'success')
            return redirect(url_for('share.ver_carpeta_admin', carpeta_id=carpeta_id))
        except Exception as e:
            app.logger.error(f"Error actualizando carpeta share: {e}")
            flash('No se pudo actualizar la carpeta.', 'error')

    return render_template('share/admin_carpeta_form.html',
                           datosApp=datosApp, carpeta=carpeta, modo='editar')


@share_bp.route('/admin/compartir/carpeta/<int:carpeta_id>/subcarpeta', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SHARE)
def crear_subcarpeta(carpeta_id):
    padre = _get_carpeta(carpeta_id)
    if not padre:
        flash('Carpeta padre no encontrada.', 'error')
        return redirect(url_for('share.gestion_carpetas'))

    nombre = (request.form.get('nombre') or '').strip()
    if not nombre:
        flash('El nombre de la subcarpeta es obligatorio.', 'error')
        return redirect(url_for('share.ver_carpeta_admin', carpeta_id=carpeta_id))

    try:
        with get_db_cursor() as cur:
            cur.execute("""
                INSERT INTO share_carpetas (parent_id, nombre, creado_por)
                VALUES (%s, %s, %s)
            """, (carpeta_id, nombre, session.get('usuario_id')))
        flash(f'Subcarpeta "{nombre}" creada.', 'success')
    except Exception as e:
        app.logger.error(f"Error creando subcarpeta share: {e}")
        flash('No se pudo crear la subcarpeta.', 'error')

    return redirect(url_for('share.ver_carpeta_admin', carpeta_id=carpeta_id))


@share_bp.route('/admin/compartir/carpeta/<int:carpeta_id>/subir', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SHARE)
def subir_archivo_admin(carpeta_id):
    carpeta = _get_carpeta(carpeta_id)
    if not carpeta:
        flash('Carpeta no encontrada.', 'error')
        return redirect(url_for('share.gestion_carpetas'))

    raiz_id = _carpeta_raiz_id(carpeta_id)
    if not raiz_id:
        flash('Estructura de carpeta invalida.', 'error')
        return redirect(url_for('share.gestion_carpetas'))

    files = request.files.getlist('archivos')
    if not files or all(not f.filename for f in files):
        flash('Selecciona al menos un archivo.', 'error')
        return redirect(url_for('share.ver_carpeta_admin', carpeta_id=carpeta_id))

    subidos = 0
    for f in files:
        if not f or not f.filename:
            continue
        if not _allowed_file(f.filename):
            flash(f'Archivo "{f.filename}" omitido (extension no permitida).', 'warning')
            continue
        _guardar_archivo(f, carpeta_id, raiz_id, subido_por_admin=session.get('usuario_id'))
        subidos += 1

    if subidos:
        flash(f'{subidos} archivo(s) subido(s).', 'success')
    return redirect(url_for('share.ver_carpeta_admin', carpeta_id=carpeta_id))


@share_bp.route('/admin/compartir/carpeta/<int:carpeta_id>/importar-carpeta', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SHARE)
def importar_carpeta_admin(carpeta_id):
    carpeta = _get_carpeta(carpeta_id)
    if not carpeta:
        flash('Carpeta destino no encontrada.', 'error')
        return redirect(url_for('share.gestion_carpetas'))

    raiz_id = _carpeta_raiz_id(carpeta_id)
    if not raiz_id:
        flash('Estructura de carpeta invalida.', 'error')
        return redirect(url_for('share.gestion_carpetas'))

    files = request.files.getlist('carpeta_archivos')
    if not files or all(not f.filename for f in files):
        flash('Selecciona una carpeta con archivos.', 'error')
        return redirect(url_for('share.ver_carpeta_admin', carpeta_id=carpeta_id))

    try:
        rutas_relativas = json.loads(request.form.get('rutas_relativas_json') or '[]')
    except ValueError:
        rutas_relativas = []

    subidos = 0
    subcarpetas_creadas = 0

    for index, archivo in enumerate(files):
        if not archivo or not archivo.filename:
            continue

        ruta_relativa = rutas_relativas[index] if index < len(rutas_relativas) else ''
        subcarpetas, nombre_original = _parsear_ruta_importada(ruta_relativa, archivo.filename)
        if subcarpetas is None or not nombre_original:
            flash(f'Archivo "{archivo.filename}" omitido (ruta no valida).', 'warning')
            continue

        if not _allowed_file(nombre_original):
            flash(f'Archivo "{nombre_original}" omitido (extension no permitida).', 'warning')
            continue

        destino_id, creadas = _resolver_carpeta_destino_importacion(carpeta_id, subcarpetas)
        if not destino_id:
            flash(f'No se pudo preparar la ruta para "{nombre_original}".', 'error')
            continue

        resultado = _guardar_archivo(
            archivo,
            destino_id,
            raiz_id,
            subido_por_admin=session.get('usuario_id'),
            nombre_original=nombre_original,
        )
        if resultado:
            subidos += 1
            subcarpetas_creadas += creadas

    if subidos:
        flash(f'Se importaron {subidos} archivo(s) y {subcarpetas_creadas} subcarpeta(s).', 'success')
    else:
        flash('No se pudo importar ningun archivo de la carpeta seleccionada.', 'warning')

    return redirect(url_for('share.ver_carpeta_admin', carpeta_id=carpeta_id))


def _guardar_archivo(file_storage, carpeta_id, raiz_id, subido_por_admin=None,
                     subido_por_cliente=None, nombre_original=None):
    """Guarda fisicamente y registra en BD un archivo. Devuelve dict con info."""
    nombre_original = (nombre_original or file_storage.filename or '').strip()
    base = secure_filename(nombre_original) or 'archivo'

    file_storage.stream.seek(0, os.SEEK_END)
    tamano = file_storage.stream.tell()
    file_storage.stream.seek(0)

    if tamano > MAX_UPLOAD_BYTES:
        flash(f'"{nombre_original}" excede el tamano maximo de {_format_bytes(MAX_UPLOAD_BYTES)}.', 'warning')
        return None

    folder = _carpeta_dir(raiz_id)
    mime = file_storage.mimetype or 'application/octet-stream'

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                INSERT INTO share_archivos
                    (carpeta_id, nombre_original, nombre_almacenado,
                     tamano_bytes, mime_type, subido_por_admin, subido_por_cliente)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (carpeta_id, nombre_original, '__pendiente__',
                  tamano, mime, subido_por_admin, subido_por_cliente))
            archivo_id = cur.fetchone()['id']

            nombre_almacenado = f'{archivo_id}__{base}'
            full_path = os.path.join(folder, nombre_almacenado)
            file_storage.save(full_path)

            cur.execute("""
                UPDATE share_archivos SET nombre_almacenado = %s WHERE id = %s
            """, (nombre_almacenado, archivo_id))
        return {'id': archivo_id, 'nombre_almacenado': nombre_almacenado}
    except Exception as e:
        app.logger.error(f"Error guardando archivo share: {e}")
        flash(f'No se pudo guardar "{nombre_original}".', 'error')
        return None


@share_bp.route('/admin/compartir/archivo/<int:archivo_id>/eliminar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SHARE)
def eliminar_archivo(archivo_id):
    redirect_to = request.form.get('volver') or url_for('share.gestion_carpetas')
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT * FROM share_archivos WHERE id = %s", (archivo_id,))
            arch = cur.fetchone()
            if not arch:
                flash('Archivo no encontrado.', 'error')
                return redirect(redirect_to)
            raiz_id = _carpeta_raiz_id(arch['carpeta_id'])
            if raiz_id:
                fpath = _resolver_archivo_path(raiz_id, arch['nombre_almacenado'])
                if os.path.isfile(fpath):
                    try:
                        os.remove(fpath)
                    except Exception as e:
                        app.logger.warning(f"No se pudo borrar archivo fisico {fpath}: {e}")
            cur.execute("DELETE FROM share_archivos WHERE id = %s", (archivo_id,))
        flash('Archivo eliminado.', 'success')
    except Exception as e:
        app.logger.error(f"Error eliminando archivo share: {e}")
        flash('No se pudo eliminar el archivo.', 'error')
    return redirect(redirect_to)


@share_bp.route('/admin/compartir/carpeta/<int:carpeta_id>/eliminar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SHARE)
def eliminar_carpeta(carpeta_id):
    carpeta = _get_carpeta(carpeta_id)
    if not carpeta:
        flash('Carpeta no encontrada.', 'error')
        return redirect(url_for('share.gestion_carpetas'))

    es_raiz = carpeta['parent_id'] is None
    raiz_id = carpeta_id if es_raiz else _carpeta_raiz_id(carpeta_id)
    parent_id = carpeta['parent_id']
    archivos_subarbol = []

    if raiz_id and not es_raiz:
        try:
            archivos_subarbol = _listar_archivos_subarbol(carpeta_id)
        except Exception as e:
            app.logger.error(f"Error listando archivos del subarbol share: {e}")
            flash('No se pudo preparar el borrado de la carpeta.', 'error')
            return redirect(url_for('share.ver_carpeta_admin', carpeta_id=parent_id))

    try:
        with get_db_cursor() as cur:
            cur.execute("DELETE FROM share_carpetas WHERE id = %s", (carpeta_id,))
        if es_raiz and raiz_id:
            _eliminar_carpeta_disco(raiz_id)
        elif raiz_id and archivos_subarbol:
            _eliminar_archivos_fisicos(raiz_id, archivos_subarbol)
        flash('Carpeta eliminada.', 'success')
    except Exception as e:
        app.logger.error(f"Error eliminando carpeta share: {e}")
        flash('No se pudo eliminar la carpeta.', 'error')

    if parent_id:
        return redirect(url_for('share.ver_carpeta_admin', carpeta_id=parent_id))
    return redirect(url_for('share.gestion_carpetas'))


@share_bp.route('/admin/compartir/carpeta/<int:carpeta_id>/regenerar-token', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SHARE)
def regenerar_token(carpeta_id):
    carpeta = _get_carpeta(carpeta_id)
    if not carpeta or carpeta['parent_id'] is not None:
        flash('Solo se puede regenerar el token de carpetas raiz.', 'error')
        return redirect(url_for('share.gestion_carpetas'))

    nuevo = _generar_token()
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                UPDATE share_carpetas SET token = %s, fecha_actualizacion = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (nuevo, carpeta_id))
        flash('Token regenerado. El link anterior ya no funciona.', 'success')
    except Exception as e:
        app.logger.error(f"Error regenerando token share: {e}")
        flash('No se pudo regenerar el token.', 'error')
    return redirect(url_for('share.ver_carpeta_admin', carpeta_id=carpeta_id))


@share_bp.route('/admin/compartir/carpeta/<int:carpeta_id>/accesos')
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SHARE)
def historial_accesos(carpeta_id):
    datosApp = get_data_app()
    carpeta = _get_carpeta(carpeta_id)
    if not carpeta or carpeta['parent_id'] is not None:
        flash('El historial solo aplica a carpetas raiz.', 'error')
        return redirect(url_for('share.gestion_carpetas'))

    accesos = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT a.*, ar.nombre_original AS archivo_nombre
                FROM share_accesos a
                LEFT JOIN share_archivos ar ON ar.id = a.archivo_id
                WHERE a.carpeta_raiz_id = %s
                ORDER BY a.fecha DESC
                LIMIT 500
            """, (carpeta_id,))
            accesos = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        app.logger.error(f"Error listando accesos share: {e}")

    return render_template('share/admin_accesos.html',
                           datosApp=datosApp, carpeta=carpeta, accesos=accesos)


# ─────────────────────────────────────────────────────────
# Rutas PUBLICAS (cliente)
# ─────────────────────────────────────────────────────────

@share_bp.route('/c/<token>')
def publico_raiz(token):
    return _render_publico(token, carpeta_id=None)


@share_bp.route('/c/<token>/<int:carpeta_id>')
def publico_carpeta(token, carpeta_id):
    return _render_publico(token, carpeta_id=carpeta_id)


def _render_publico(token, carpeta_id=None):
    raiz = _get_carpeta_por_token(token)
    if not raiz:
        return render_template('share/publico_vencido.html', motivo='no_existe'), 404

    if _esta_vencida(raiz):
        return render_template('share/publico_vencido.html', motivo='vencida'), 410

    if raiz['clave_hash'] and not _clave_validada(raiz):
        return redirect(url_for('share.publico_clave', token=token,
                                next_id=carpeta_id or ''))

    # Si pidio una subcarpeta, validar pertenencia al arbol
    actual = raiz
    if carpeta_id:
        if not _es_descendiente(carpeta_id, raiz['id']):
            abort(404)
        actual = _get_carpeta(carpeta_id)
        if not actual:
            abort(404)

    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT id, nombre FROM share_carpetas
            WHERE parent_id = %s
            ORDER BY nombre
        """, (actual['id'],))
        subcarpetas = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT id, nombre_original, tamano_bytes, fecha_subida
            FROM share_archivos
            WHERE carpeta_id = %s
            ORDER BY fecha_subida DESC
        """, (actual['id'],))
        archivos = []
        for row in cur.fetchall():
            d = dict(row)
            d['tamano_fmt'] = _format_bytes(d.get('tamano_bytes'))
            d['icono'] = _icono_archivo(d['nombre_original'])
            archivos.append(d)

    _registrar_acceso(raiz['id'], None, 'view')

    crumbs = _breadcrumbs(actual['id'])
    return render_template(
        'share/publico_carpeta.html',
        token=token,
        carpeta_raiz=raiz,
        carpeta_actual=actual,
        es_raiz=actual['id'] == raiz['id'],
        breadcrumbs=crumbs,
        subcarpetas=subcarpetas,
        archivos=archivos,
        permitir_subida=bool(actual['permitir_subida']),
    )


@share_bp.route('/c/<token>/clave', methods=['GET', 'POST'])
def publico_clave(token):
    raiz = _get_carpeta_por_token(token)
    if not raiz:
        return render_template('share/publico_vencido.html', motivo='no_existe'), 404
    if _esta_vencida(raiz):
        return render_template('share/publico_vencido.html', motivo='vencida'), 410
    if not raiz['clave_hash']:
        return redirect(url_for('share.publico_raiz', token=token))

    next_id = request.values.get('next_id') or ''
    error = None

    if request.method == 'POST':
        clave = (request.form.get('clave') or '').strip()
        if clave and check_password_hash(raiz['clave_hash'], clave):
            session[f'share_ok_{token}'] = raiz['clave_hash']
            if next_id:
                try:
                    return redirect(url_for('share.publico_carpeta',
                                            token=token, carpeta_id=int(next_id)))
                except ValueError:
                    pass
            return redirect(url_for('share.publico_raiz', token=token))
        error = 'Clave incorrecta. Intenta de nuevo.'

    return render_template('share/publico_clave.html',
                           token=token,
                           carpeta_raiz=raiz,
                           error=error,
                           next_id=next_id)


@share_bp.route('/c/<token>/descargar/<int:archivo_id>')
def publico_descargar(token, archivo_id):
    raiz = _get_carpeta_por_token(token)
    if not raiz:
        abort(404)
    if _esta_vencida(raiz):
        return render_template('share/publico_vencido.html', motivo='vencida'), 410
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM share_archivos WHERE id = %s", (archivo_id,))
        arch = cur.fetchone()
    if not arch:
        abort(404)
    if not _es_descendiente(arch['carpeta_id'], raiz['id']):
        abort(404)
    if raiz['clave_hash'] and not _clave_validada(raiz):
        return redirect(url_for('share.publico_clave', token=token, next_id=arch['carpeta_id']))

    file_path = _resolver_archivo_path(raiz['id'], arch['nombre_almacenado'])
    if not os.path.isfile(file_path):
        abort(404)

    _registrar_acceso(raiz['id'], archivo_id, 'download')

    return send_from_directory(
        os.path.dirname(file_path),
        os.path.basename(file_path),
        as_attachment=True,
        download_name=arch['nombre_original'],
    )


@share_bp.route('/c/<token>/subir/<int:carpeta_id>', methods=['POST'])
def publico_subir(token, carpeta_id):
    raiz = _get_carpeta_por_token(token)
    if not raiz:
        abort(404)
    if _esta_vencida(raiz):
        return render_template('share/publico_vencido.html', motivo='vencida'), 410
    carpeta = _get_carpeta(carpeta_id)
    if not carpeta:
        abort(404)
    if not _es_descendiente(carpeta_id, raiz['id']):
        abort(404)
    if not carpeta['permitir_subida']:
        flash('La subida no esta habilitada para esta carpeta.', 'error')
        if carpeta_id == raiz['id']:
            return redirect(url_for('share.publico_raiz', token=token))
        return redirect(url_for('share.publico_carpeta', token=token, carpeta_id=carpeta_id))
    if raiz['clave_hash'] and not _clave_validada(raiz):
        return redirect(url_for('share.publico_clave', token=token, next_id=carpeta_id))

    nombre_cliente = (request.form.get('nombre_cliente') or 'Cliente')[:120].strip() or 'Cliente'
    files = request.files.getlist('archivos')
    if not files or all(not f.filename for f in files):
        flash('Selecciona al menos un archivo.', 'error')
        return redirect(url_for('share.publico_carpeta', token=token, carpeta_id=carpeta_id))

    subidos = 0
    for f in files:
        if not f or not f.filename:
            continue
        if not _allowed_file(f.filename):
            flash(f'Archivo "{f.filename}" omitido (extension no permitida).', 'warning')
            continue
        result = _guardar_archivo(f, carpeta_id, raiz['id'],
                                  subido_por_cliente=nombre_cliente)
        if result:
            _registrar_acceso(raiz['id'], result['id'], 'upload')
            subidos += 1

    if subidos:
        flash(f'{subidos} archivo(s) subido(s) correctamente.', 'success')
    return redirect(url_for('share.publico_carpeta', token=token, carpeta_id=carpeta_id))
