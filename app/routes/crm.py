"""
routes/crm.py — Blueprint CRM de Contactos.

Gestiona Clientes, Proveedores, Leads y Socios con CRUD de contactos,
registro de actividades/seguimientos y tareas pendientes.
"""

import os
from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
from database import get_db_cursor
from helpers import get_data_app
from security import rol_requerido

crm_bp = Blueprint('crm', __name__, url_prefix='/admin/crm')

UPLOAD_DIR = os.path.join('static', 'crm', 'fotos')
ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}


@crm_bp.context_processor
def inject_common_data():
    return dict(datosApp=get_data_app())


# ------------------------------------------------------------------
# Helpers internos
# ------------------------------------------------------------------

def _guardar_foto(archivo, contacto_id):
    """Guarda foto de contacto y retorna la ruta relativa."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(secure_filename(archivo.filename))[1].lower()
    if ext not in ALLOWED_EXT:
        return None
    filename = f"{contacto_id}{ext}"
    archivo.save(os.path.join(UPLOAD_DIR, filename))
    return f"crm/fotos/{filename}"


def _eliminar_foto(foto_path):
    """Elimina foto del disco si existe."""
    if foto_path:
        ruta = os.path.join('static', foto_path)
        if os.path.isfile(ruta):
            try:
                os.remove(ruta)
            except OSError:
                pass


# ------------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------------

@crm_bp.route('/')
@rol_requerido(1)
def crm_dashboard():
    with get_db_cursor(dict_cursor=True) as cur:
        # Conteo por tipo
        cur.execute("""
            SELECT tipo, COUNT(*) AS total
            FROM crm_contactos WHERE activo = TRUE
            GROUP BY tipo
        """)
        conteos_raw = cur.fetchall()

        # Tareas vencidas
        cur.execute("""
            SELECT COUNT(*) AS total FROM crm_tareas
            WHERE estado = 'pendiente' AND fecha_limite < CURRENT_DATE
        """)
        tareas_vencidas = cur.fetchone()['total']

        # Tareas para hoy
        cur.execute("""
            SELECT COUNT(*) AS total FROM crm_tareas
            WHERE estado = 'pendiente' AND fecha_limite = CURRENT_DATE
        """)
        tareas_hoy = cur.fetchone()['total']

        # Actividades recientes (10)
        cur.execute("""
            SELECT a.*, c.nombre AS contacto_nombre, c.tipo AS contacto_tipo
            FROM crm_actividades a
            JOIN crm_contactos c ON a.contacto_id = c.id
            ORDER BY a.fecha_actividad DESC
            LIMIT 10
        """)
        actividades_recientes = cur.fetchall()

        # Próximas tareas (5)
        cur.execute("""
            SELECT t.*, c.nombre AS contacto_nombre
            FROM crm_tareas t
            JOIN crm_contactos c ON t.contacto_id = c.id
            WHERE t.estado = 'pendiente'
            ORDER BY t.fecha_limite ASC NULLS LAST
            LIMIT 5
        """)
        proximas_tareas = cur.fetchall()

    # Construir dict de conteos
    conteos = {r['tipo']: r['total'] for r in conteos_raw}
    total_contactos = sum(conteos.values())

    return render_template(
        'crm_dashboard.html',
        conteos=conteos,
        total_contactos=total_contactos,
        tareas_vencidas=tareas_vencidas,
        tareas_hoy=tareas_hoy,
        actividades_recientes=actividades_recientes,
        proximas_tareas=proximas_tareas,
        hoy=date.today(),
    )


# ------------------------------------------------------------------
# Contactos — Lista
# ------------------------------------------------------------------

@crm_bp.route('/contactos')
@rol_requerido(1)
def crm_contactos_lista():
    tipo_filtro = request.args.get('tipo')
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT id, nombre, empresa, tipo, email, telefono, ciudad, foto_path, created_at
            FROM crm_contactos
            WHERE activo = TRUE
              AND (%s IS NULL OR tipo = %s)
            ORDER BY nombre ASC
        """, (tipo_filtro, tipo_filtro))
        contactos = cur.fetchall()

    return render_template('crm_contactos.html', contactos=contactos, tipo_filtro=tipo_filtro)


# ------------------------------------------------------------------
# Contactos — Crear
# ------------------------------------------------------------------

@crm_bp.route('/contactos/crear', methods=['GET', 'POST'])
@rol_requerido(1)
def crm_contacto_crear():
    if request.method == 'POST':
        tipo      = request.form.get('tipo')
        nombre    = request.form.get('nombre', '').strip()
        empresa   = request.form.get('empresa', '').strip() or None
        cargo     = request.form.get('cargo', '').strip() or None
        email     = request.form.get('email', '').strip() or None
        telefono  = request.form.get('telefono', '').strip() or None
        whatsapp  = request.form.get('whatsapp', '').strip() or None
        sitio_web = request.form.get('sitio_web', '').strip() or None
        direccion = request.form.get('direccion', '').strip() or None
        ciudad    = request.form.get('ciudad', '').strip() or None
        usuario_id = request.form.get('usuario_id') or None
        notas     = request.form.get('notas', '').strip() or None
        origen    = request.form.get('origen', '').strip() or None

        if not nombre or not tipo:
            flash('El nombre y el tipo son obligatorios.', 'warning')
            return redirect(url_for('crm.crm_contacto_crear'))

        try:
            with get_db_cursor() as cur:
                cur.execute("""
                    INSERT INTO crm_contactos
                        (tipo, nombre, empresa, cargo, email, telefono, whatsapp,
                         sitio_web, direccion, ciudad, usuario_id, notas, origen)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id
                """, (tipo, nombre, empresa, cargo, email, telefono, whatsapp,
                      sitio_web, direccion, ciudad, usuario_id, notas, origen))
                nuevo_id = cur.fetchone()[0]

                # Foto
                foto = request.files.get('foto')
                if foto and foto.filename:
                    foto_path = _guardar_foto(foto, nuevo_id)
                    if foto_path:
                        cur.execute(
                            "UPDATE crm_contactos SET foto_path = %s WHERE id = %s",
                            (foto_path, nuevo_id)
                        )

            flash('Contacto creado exitosamente.', 'success')
            return redirect(url_for('crm.crm_contacto_ver', id=nuevo_id))
        except Exception as e:
            flash(f'Error al crear contacto: {str(e)}', 'danger')

    # GET — cargar usuarios para el select
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT id, nombre, email FROM usuarios
            WHERE estado = 'habilitado'
            ORDER BY nombre ASC
        """)
        usuarios = cur.fetchall()

    return render_template('crm_contacto_form.html', modo='crear', contacto=None, usuarios=usuarios)


# ------------------------------------------------------------------
# Contactos — Ver
# ------------------------------------------------------------------

@crm_bp.route('/contactos/<int:id>')
@rol_requerido(1)
def crm_contacto_ver(id):
    with get_db_cursor(dict_cursor=True) as cur:
        # 1. Datos contacto
        cur.execute("""
            SELECT c.*, u.email AS usuario_email, u.nombre AS usuario_nombre
            FROM crm_contactos c
            LEFT JOIN usuarios u ON c.usuario_id = u.id
            WHERE c.id = %s
        """, (id,))
        contacto = cur.fetchone()

        if not contacto:
            flash('Contacto no encontrado.', 'warning')
            return redirect(url_for('crm.crm_contactos_lista'))

        # 2. Actividades
        cur.execute("""
            SELECT a.*, u.nombre AS registrado_por
            FROM crm_actividades a
            LEFT JOIN usuarios u ON a.usuario_id = u.id
            WHERE a.contacto_id = %s
            ORDER BY a.fecha_actividad DESC
        """, (id,))
        actividades = cur.fetchall()

        # 3. Tareas
        cur.execute("""
            SELECT t.*, u.nombre AS asignado_nombre
            FROM crm_tareas t
            LEFT JOIN usuarios u ON t.asignado_a = u.id
            WHERE t.contacto_id = %s
            ORDER BY
                CASE t.estado WHEN 'pendiente' THEN 0 ELSE 1 END,
                t.fecha_limite ASC NULLS LAST
        """, (id,))
        tareas = cur.fetchall()

        # 4. Pedidos vinculados por email del contacto
        email = contacto.get('email') or ''
        if email:
            cur.execute("""
                SELECT id, referencia_pedido, estado_pago, estado_envio,
                       monto_total, fecha_creacion
                FROM pedidos
                WHERE cliente_email = %s
                ORDER BY fecha_creacion DESC
                LIMIT 20
            """, (email,))
            pedidos = cur.fetchall()
        else:
            pedidos = []

    return render_template(
        'crm_contacto_ver.html',
        contacto=contacto,
        actividades=actividades,
        tareas=tareas,
        pedidos=pedidos,
        hoy=date.today(),
    )


# ------------------------------------------------------------------
# Contactos — Editar
# ------------------------------------------------------------------

@crm_bp.route('/contactos/<int:id>/editar', methods=['GET', 'POST'])
@rol_requerido(1)
def crm_contacto_editar(id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM crm_contactos WHERE id = %s", (id,))
        contacto = cur.fetchone()

    if not contacto:
        flash('Contacto no encontrado.', 'warning')
        return redirect(url_for('crm.crm_contactos_lista'))

    if request.method == 'POST':
        tipo      = request.form.get('tipo')
        nombre    = request.form.get('nombre', '').strip()
        empresa   = request.form.get('empresa', '').strip() or None
        cargo     = request.form.get('cargo', '').strip() or None
        email     = request.form.get('email', '').strip() or None
        telefono  = request.form.get('telefono', '').strip() or None
        whatsapp  = request.form.get('whatsapp', '').strip() or None
        sitio_web = request.form.get('sitio_web', '').strip() or None
        direccion = request.form.get('direccion', '').strip() or None
        ciudad    = request.form.get('ciudad', '').strip() or None
        usuario_id = request.form.get('usuario_id') or None
        notas     = request.form.get('notas', '').strip() or None
        origen    = request.form.get('origen', '').strip() or None

        if not nombre or not tipo:
            flash('El nombre y el tipo son obligatorios.', 'warning')
            return redirect(url_for('crm.crm_contacto_editar', id=id))

        # Manejar foto nueva
        foto_path = contacto['foto_path']
        foto = request.files.get('foto')
        if foto and foto.filename:
            _eliminar_foto(foto_path)
            nueva_ruta = _guardar_foto(foto, id)
            if nueva_ruta:
                foto_path = nueva_ruta

        try:
            with get_db_cursor() as cur:
                cur.execute("""
                    UPDATE crm_contactos SET
                        tipo=%s, nombre=%s, empresa=%s, cargo=%s, email=%s,
                        telefono=%s, whatsapp=%s, sitio_web=%s, direccion=%s,
                        ciudad=%s, usuario_id=%s, notas=%s, origen=%s,
                        foto_path=%s, updated_at=CURRENT_TIMESTAMP
                    WHERE id=%s
                """, (tipo, nombre, empresa, cargo, email, telefono, whatsapp,
                      sitio_web, direccion, ciudad, usuario_id, notas, origen,
                      foto_path, id))

            flash('Contacto actualizado.', 'success')
            return redirect(url_for('crm.crm_contacto_ver', id=id))
        except Exception as e:
            flash(f'Error al actualizar contacto: {str(e)}', 'danger')

    # GET
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT id, nombre, email FROM usuarios
            WHERE estado = 'habilitado'
            ORDER BY nombre ASC
        """)
        usuarios = cur.fetchall()

    return render_template('crm_contacto_form.html', modo='editar', contacto=contacto, usuarios=usuarios)


# ------------------------------------------------------------------
# Contactos — Eliminar (soft delete)
# ------------------------------------------------------------------

@crm_bp.route('/contactos/<int:id>/eliminar', methods=['POST'])
@rol_requerido(1)
def crm_contacto_eliminar(id):
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                UPDATE crm_contactos
                SET activo = FALSE, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (id,))
        flash('Contacto eliminado.', 'success')
    except Exception as e:
        flash(f'Error al eliminar: {str(e)}', 'danger')
    return redirect(url_for('crm.crm_contactos_lista'))


# ------------------------------------------------------------------
# Actividades — Crear
# ------------------------------------------------------------------

@crm_bp.route('/contactos/<int:id>/actividades/nueva', methods=['GET', 'POST'])
@rol_requerido(1)
def crm_actividad_crear(id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT id, nombre FROM crm_contactos WHERE id = %s", (id,))
        contacto = cur.fetchone()

    if not contacto:
        flash('Contacto no encontrado.', 'warning')
        return redirect(url_for('crm.crm_contactos_lista'))

    if request.method == 'POST':
        tipo        = request.form.get('tipo')
        asunto      = request.form.get('asunto', '').strip()
        descripcion = request.form.get('descripcion', '').strip() or None
        fecha_str   = request.form.get('fecha_actividad')
        usuario_id  = session.get('id')

        if not tipo or not asunto:
            flash('Tipo y asunto son obligatorios.', 'warning')
            return redirect(url_for('crm.crm_actividad_crear', id=id))

        try:
            fecha_actividad = datetime.strptime(fecha_str, '%Y-%m-%dT%H:%M') if fecha_str else datetime.now()
        except ValueError:
            fecha_actividad = datetime.now()

        try:
            with get_db_cursor() as cur:
                cur.execute("""
                    INSERT INTO crm_actividades
                        (contacto_id, tipo, asunto, descripcion, fecha_actividad, usuario_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (id, tipo, asunto, descripcion, fecha_actividad, usuario_id))
            flash('Actividad registrada.', 'success')
            return redirect(url_for('crm.crm_contacto_ver', id=id))
        except Exception as e:
            flash(f'Error al registrar actividad: {str(e)}', 'danger')

    ahora = datetime.now().strftime('%Y-%m-%dT%H:%M')
    return render_template('crm_actividad_form.html', contacto=contacto, ahora=ahora)


# ------------------------------------------------------------------
# Actividades — Eliminar
# ------------------------------------------------------------------

@crm_bp.route('/actividades/<int:id>/eliminar', methods=['POST'])
@rol_requerido(1)
def crm_actividad_eliminar(id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT contacto_id FROM crm_actividades WHERE id = %s", (id,))
        row = cur.fetchone()

    contacto_id = row['contacto_id'] if row else None

    try:
        with get_db_cursor() as cur:
            cur.execute("DELETE FROM crm_actividades WHERE id = %s", (id,))
        flash('Actividad eliminada.', 'success')
    except Exception as e:
        flash(f'Error al eliminar actividad: {str(e)}', 'danger')

    if contacto_id:
        return redirect(url_for('crm.crm_contacto_ver', id=contacto_id))
    return redirect(url_for('crm.crm_contactos_lista'))


# ------------------------------------------------------------------
# Tareas — Lista global
# ------------------------------------------------------------------

@crm_bp.route('/tareas')
@rol_requerido(1)
def crm_tareas_lista():
    estado = request.args.get('estado', 'pendiente')
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT t.*, c.nombre AS contacto_nombre, c.tipo AS contacto_tipo,
                   u.nombre AS asignado_nombre
            FROM crm_tareas t
            JOIN crm_contactos c ON t.contacto_id = c.id
            LEFT JOIN usuarios u ON t.asignado_a = u.id
            WHERE c.activo = TRUE
              AND (%s = 'todas' OR t.estado = %s)
            ORDER BY
                CASE t.estado WHEN 'pendiente' THEN 0 ELSE 1 END,
                t.fecha_limite ASC NULLS LAST
        """, (estado, estado))
        tareas = cur.fetchall()

    return render_template('crm_tareas.html', tareas=tareas, estado_filtro=estado, hoy=date.today())


# ------------------------------------------------------------------
# Tareas — Crear
# ------------------------------------------------------------------

@crm_bp.route('/contactos/<int:id>/tareas/nueva', methods=['GET', 'POST'])
@rol_requerido(1)
def crm_tarea_crear(id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT id, nombre FROM crm_contactos WHERE id = %s", (id,))
        contacto = cur.fetchone()

    if not contacto:
        flash('Contacto no encontrado.', 'warning')
        return redirect(url_for('crm.crm_contactos_lista'))

    if request.method == 'POST':
        titulo      = request.form.get('titulo', '').strip()
        descripcion = request.form.get('descripcion', '').strip() or None
        prioridad   = request.form.get('prioridad', 'media')
        fecha_limite = request.form.get('fecha_limite') or None
        asignado_a  = request.form.get('asignado_a') or None
        creado_por  = session.get('id')

        if not titulo:
            flash('El título es obligatorio.', 'warning')
            return redirect(url_for('crm.crm_tarea_crear', id=id))

        try:
            with get_db_cursor() as cur:
                cur.execute("""
                    INSERT INTO crm_tareas
                        (contacto_id, titulo, descripcion, prioridad, fecha_limite,
                         asignado_a, creado_por)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (id, titulo, descripcion, prioridad, fecha_limite, asignado_a, creado_por))
            flash('Tarea creada.', 'success')
            return redirect(url_for('crm.crm_contacto_ver', id=id))
        except Exception as e:
            flash(f'Error al crear tarea: {str(e)}', 'danger')

    # GET — usuarios staff/admin para asignar
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT id, nombre FROM usuarios
            WHERE rol_id IN (1, 2)
            ORDER BY nombre ASC
        """)
        usuarios = cur.fetchall()

    return render_template('crm_tarea_form.html', contacto=contacto, usuarios=usuarios)


# ------------------------------------------------------------------
# Tareas — Completar
# ------------------------------------------------------------------

@crm_bp.route('/tareas/<int:id>/completar', methods=['POST'])
@rol_requerido(1)
def crm_tarea_completar(id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT contacto_id FROM crm_tareas WHERE id = %s", (id,))
        row = cur.fetchone()

    contacto_id = row['contacto_id'] if row else None

    try:
        with get_db_cursor() as cur:
            cur.execute("""
                UPDATE crm_tareas
                SET estado = 'completada', completada_en = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (id,))
        flash('Tarea marcada como completada.', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')

    if contacto_id:
        return redirect(url_for('crm.crm_contacto_ver', id=contacto_id))
    return redirect(url_for('crm.crm_tareas_lista'))


# ------------------------------------------------------------------
# Tareas — Eliminar
# ------------------------------------------------------------------

@crm_bp.route('/tareas/<int:id>/eliminar', methods=['POST'])
@rol_requerido(1)
def crm_tarea_eliminar(id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT contacto_id FROM crm_tareas WHERE id = %s", (id,))
        row = cur.fetchone()

    contacto_id = row['contacto_id'] if row else None

    try:
        with get_db_cursor() as cur:
            cur.execute("DELETE FROM crm_tareas WHERE id = %s", (id,))
        flash('Tarea eliminada.', 'success')
    except Exception as e:
        flash(f'Error al eliminar tarea: {str(e)}', 'danger')

    if contacto_id:
        return redirect(url_for('crm.crm_contacto_ver', id=contacto_id))
    return redirect(url_for('crm.crm_tareas_lista'))
