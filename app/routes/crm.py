"""
routes/crm.py — Blueprint CRM de Contactos.

Gestiona Clientes, Proveedores, Leads y Socios con CRUD de contactos,
registro de actividades/seguimientos y tareas pendientes.
"""

import os
from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from helpers_gmail import enviar_email_gmail
from werkzeug.utils import secure_filename
from database import get_db_cursor
from helpers import get_data_app
from security import rol_requerido, ADMIN_STAFF

crm_bp = Blueprint('crm', __name__, url_prefix='/admin/crm')

UPLOAD_DIR = os.path.join('static', 'crm', 'fotos')
ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}


def _sync_google_calendar(tabla, registro_id, usuario_id, summary, description, start_date, end_date, invitados_raw):
    """Sincroniza un registro CRM con Google Calendar si el usuario tiene token."""
    from helpers_google import session_user_tiene_google, crear_evento
    if not session_user_tiene_google():
        return
    try:
        invitados = [e.strip() for e in invitados_raw.split(',') if e.strip()] if invitados_raw else []
        event_id = crear_evento(
            usuario_id=usuario_id,
            summary=summary,
            description=description or '',
            start_date=start_date,
            end_date=end_date,
            attendees=invitados,
        )
        if event_id:
            with get_db_cursor() as cur:
                cur.execute(f"""
                    UPDATE {tabla}
                    SET google_event_id = %s, invitados_emails = %s
                    WHERE id = %s
                """, (event_id, ','.join(invitados) or None, registro_id))
    except Exception:
        entity = 'Actividad' if tabla == 'crm_actividades' else 'Tarea'
        flash(f'{entity} registrada, pero no se pudo sincronizar con Google Calendar.', 'warning')


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
@rol_requerido(ADMIN_STAFF)
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

    from helpers_google import session_user_tiene_google
    return render_template(
        'crm_dashboard.html',
        conteos=conteos,
        total_contactos=total_contactos,
        tareas_vencidas=tareas_vencidas,
        tareas_hoy=tareas_hoy,
        actividades_recientes=actividades_recientes,
        proximas_tareas=proximas_tareas,
        hoy=date.today(),
        google_conectado=session_user_tiene_google(),
    )


# ------------------------------------------------------------------
# Contactos — Lista
# ------------------------------------------------------------------

@crm_bp.route('/contactos')
@rol_requerido(ADMIN_STAFF)
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
@rol_requerido(ADMIN_STAFF)
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
@rol_requerido(ADMIN_STAFF)
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

        # 5. Cotizaciones vinculadas
        cur.execute("""
            SELECT id, cliente_nombre, total, estado, fecha AS fecha_creacion, pdf_path
              FROM cotizaciones
             WHERE crm_contacto_id = %s
             ORDER BY fecha DESC
             LIMIT 30
        """, (id,))
        cotizaciones = cur.fetchall()

        # 6. Cuentas de cobro vinculadas
        cur.execute("""
            SELECT id, consecutivo, total, fecha, pdf_path, created_at
              FROM cuentas_cobro
             WHERE crm_contacto_id = %s
             ORDER BY COALESCE(fecha, created_at::date) DESC
             LIMIT 30
        """, (id,))
        cuentas_cobro = cur.fetchall()

        # 7. Oportunidades del contacto
        cur.execute("""
            SELECT o.*, u.nombre AS asignado_nombre
              FROM crm_oportunidades o
              LEFT JOIN usuarios u ON o.asignado_a = u.id
             WHERE o.contacto_id = %s
             ORDER BY
                CASE o.etapa
                    WHEN 'prospecto'   THEN 0
                    WHEN 'calificado'  THEN 1
                    WHEN 'propuesta'   THEN 2
                    WHEN 'negociacion' THEN 3
                    WHEN 'ganada'      THEN 4
                    WHEN 'perdida'     THEN 5
                END,
                o.updated_at DESC
        """, (id,))
        oportunidades = cur.fetchall()

        # Totales para resumen
        total_comprado = sum(float(p['monto_total'] or 0) for p in pedidos
                             if (p.get('estado_pago') or '').upper() == 'APROBADO')
        total_cotizado = sum(float(c['total'] or 0) for c in cotizaciones)
        total_facturado = sum(float(c['total'] or 0) for c in cuentas_cobro)

    return render_template(
        'crm_contacto_ver.html',
        contacto=contacto,
        actividades=actividades,
        tareas=tareas,
        pedidos=pedidos,
        cotizaciones=cotizaciones,
        cuentas_cobro=cuentas_cobro,
        oportunidades=oportunidades,
        total_comprado=total_comprado,
        total_cotizado=total_cotizado,
        total_facturado=total_facturado,
        hoy=date.today(),
    )


# ------------------------------------------------------------------
# Contactos — Editar
# ------------------------------------------------------------------

@crm_bp.route('/contactos/<int:id>/editar', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
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
@rol_requerido(ADMIN_STAFF)
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
@rol_requerido(ADMIN_STAFF)
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
        usuario_id  = session.get('usuario_id')

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
                    RETURNING id
                """, (id, tipo, asunto, descripcion, fecha_actividad, usuario_id))
                actividad_id = cur.fetchone()[0]

            # Sincronizar con Google Calendar
            _sync_google_calendar(
                'crm_actividades', actividad_id, usuario_id,
                asunto, descripcion, fecha_actividad, fecha_actividad,
                request.form.get('invitados_emails', ''))

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
@rol_requerido(ADMIN_STAFF)
def crm_actividad_eliminar(id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT contacto_id, google_event_id FROM crm_actividades WHERE id = %s", (id,))
        row = cur.fetchone()

    contacto_id = row['contacto_id'] if row else None

    # Eliminar evento de Google Calendar si existe
    if row and row.get('google_event_id'):
        from helpers_google import eliminar_evento
        usuario_id = session.get('usuario_id')
        eliminar_evento(usuario_id, row['google_event_id'])

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
@rol_requerido(ADMIN_STAFF)
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
@rol_requerido(ADMIN_STAFF)
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
        creado_por  = session.get('usuario_id')
        recordatorio_diario = bool(request.form.get('recordatorio_diario'))

        if not titulo:
            flash('El título es obligatorio.', 'warning')
            return redirect(url_for('crm.crm_tarea_crear', id=id))

        try:
            with get_db_cursor() as cur:
                cur.execute("""
                    INSERT INTO crm_tareas
                        (contacto_id, titulo, descripcion, prioridad, fecha_limite,
                         asignado_a, creado_por, recordatorio_diario)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (id, titulo, descripcion, prioridad, fecha_limite,
                      asignado_a, creado_por, recordatorio_diario))
                tarea_id = cur.fetchone()[0]

            # Sincronizar con Google Calendar
            if fecha_limite:
                fl = datetime.strptime(fecha_limite, '%Y-%m-%d').date() if isinstance(fecha_limite, str) else fecha_limite
                _sync_google_calendar(
                    'crm_tareas', tarea_id, creado_por,
                    titulo, descripcion, fl, fl,
                    request.form.get('invitados_emails', ''))

            # Notificación por email al asignado
            if asignado_a:
                try:
                    with get_db_cursor(dict_cursor=True) as cur:
                        cur.execute("SELECT nombre, email FROM usuarios WHERE id = %s", (asignado_a,))
                        asignado = cur.fetchone()
                    if asignado and asignado['email']:
                        color_prioridad = {'alta': '#dc3545', 'media': '#ffc107', 'baja': '#28a745'}.get(prioridad, '#6c757d')
                        texto_prioridad = prioridad.capitalize()
                        fecha_txt = fecha_limite or 'Sin fecha'
                        desc_html = f'<p style="margin:0;color:#333;line-height:1.5;">{descripcion}</p>' if descripcion else '<p style="margin:0;color:#999;">Sin descripción</p>'
                        nota_recordatorio = ''
                        if recordatorio_diario:
                            nota_recordatorio = '''
                            <div style="background:#fff8e1;border-left:4px solid #ffc107;border-radius:0 8px 8px 0;padding:12px 16px;margin-top:16px;">
                                <p style="margin:0;color:#856404;font-size:0.9em;">
                                    <i>&#128276;</i> <strong>Recordatorio diario activado</strong> —
                                    Recibirás un correo cada mañana mientras esta tarea esté pendiente.
                                </p>
                            </div>'''

                        cuerpo_plano = (
                            f"Hola {asignado['nombre']},\n\n"
                            f"Se te ha asignado una nueva tarea:\n\n"
                            f"  Título:       {titulo}\n"
                            f"  Contacto:     {contacto['nombre']}\n"
                            f"  Prioridad:    {texto_prioridad}\n"
                            f"  Fecha límite: {fecha_txt}\n"
                        )
                        if descripcion:
                            cuerpo_plano += f"  Descripción:  {descripcion}\n"
                        if recordatorio_diario:
                            cuerpo_plano += "\nRecibirás un recordatorio diario hasta completar esta tarea.\n"

                        cuerpo_html = f"""
                        <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:600px;margin:0 auto;border:1px solid #e0e0e0;border-radius:12px;overflow:hidden;">
                            <div style="background:linear-gradient(135deg,#122C94,#091C5A);padding:24px 30px;">
                                <h2 style="color:#fff;margin:0;font-size:20px;">
                                    &#9745; Nueva tarea asignada
                                </h2>
                            </div>
                            <div style="padding:28px 30px;background:#fff;">
                                <p style="margin:0 0 18px;color:#555;font-size:1em;">
                                    Hola <strong>{asignado['nombre']}</strong>, se te ha asignado una nueva tarea:
                                </p>
                                <table style="width:100%;border-collapse:collapse;margin-bottom:16px;">
                                    <tr>
                                        <td style="padding:10px 14px;background:#f4f6fb;font-weight:600;color:#555;width:130px;border-radius:8px 0 0 0;">Título</td>
                                        <td style="padding:10px 14px;background:#f4f6fb;color:#222;font-weight:600;border-radius:0 8px 0 0;">{titulo}</td>
                                    </tr>
                                    <tr>
                                        <td style="padding:10px 14px;font-weight:600;color:#555;">Contacto</td>
                                        <td style="padding:10px 14px;color:#222;">{contacto['nombre']}</td>
                                    </tr>
                                    <tr>
                                        <td style="padding:10px 14px;background:#f4f6fb;font-weight:600;color:#555;">Prioridad</td>
                                        <td style="padding:10px 14px;background:#f4f6fb;">
                                            <span style="display:inline-block;background:{color_prioridad};color:#fff;padding:3px 12px;border-radius:12px;font-size:0.85em;font-weight:600;">{texto_prioridad}</span>
                                        </td>
                                    </tr>
                                    <tr>
                                        <td style="padding:10px 14px;font-weight:600;color:#555;">Fecha límite</td>
                                        <td style="padding:10px 14px;color:#222;">{fecha_txt}</td>
                                    </tr>
                                </table>
                                <div style="background:#f9fafb;border-left:4px solid #122C94;border-radius:0 8px 8px 0;padding:14px 18px;">
                                    <p style="margin:0 0 6px;font-weight:600;color:#555;font-size:0.8em;text-transform:uppercase;letter-spacing:0.5px;">Descripción</p>
                                    {desc_html}
                                </div>
                                {nota_recordatorio}
                            </div>
                            <div style="background:#f4f6fb;padding:14px 30px;text-align:center;font-size:12px;color:#999;">
                                Notificación automática del sistema CRM
                            </div>
                        </div>"""

                        enviar_email_gmail(
                            asignado['email'],
                            f"Nueva tarea asignada: {titulo}",
                            cuerpo_plano,
                            html=cuerpo_html
                        )
                except Exception:
                    flash('Tarea creada, pero no se pudo enviar el correo de notificación.', 'warning')

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
@rol_requerido(ADMIN_STAFF)
def crm_tarea_completar(id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(
            "SELECT contacto_id, google_event_id, titulo, creado_por FROM crm_tareas WHERE id = %s",
            (id,)
        )
        row = cur.fetchone()

    contacto_id = row['contacto_id'] if row else None

    try:
        with get_db_cursor() as cur:
            cur.execute("""
                UPDATE crm_tareas
                SET estado = 'completada', completada_en = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (id,))

        # Actualizar evento en Google Calendar
        if row and row['google_event_id']:
            try:
                from helpers_google import actualizar_evento
                actualizar_evento(
                    usuario_id=row['creado_por'],
                    event_id=row['google_event_id'],
                    summary=f"[Completada] {row['titulo']}",
                )
            except Exception:
                pass

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
@rol_requerido(ADMIN_STAFF)
def crm_tarea_eliminar(id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT contacto_id, google_event_id FROM crm_tareas WHERE id = %s", (id,))
        row = cur.fetchone()

    contacto_id = row['contacto_id'] if row else None

    # Eliminar evento de Google Calendar si existe
    if row and row.get('google_event_id'):
        from helpers_google import eliminar_evento
        usuario_id = session.get('usuario_id')
        eliminar_evento(usuario_id, row['google_event_id'])

    try:
        with get_db_cursor() as cur:
            cur.execute("DELETE FROM crm_tareas WHERE id = %s", (id,))
        flash('Tarea eliminada.', 'success')
    except Exception as e:
        flash(f'Error al eliminar tarea: {str(e)}', 'danger')

    if contacto_id:
        return redirect(url_for('crm.crm_contacto_ver', id=contacto_id))
    return redirect(url_for('crm.crm_tareas_lista'))


# ==================================================================
# F2 — PIPELINE DE OPORTUNIDADES
# ==================================================================

ETAPAS_OPORTUNIDAD = [
    ('prospecto',   'Prospecto'),
    ('calificado',  'Calificado'),
    ('propuesta',   'Propuesta'),
    ('negociacion', 'Negociación'),
    ('ganada',      'Ganada'),
    ('perdida',     'Perdida'),
]


@crm_bp.route('/pipeline')
@rol_requerido(ADMIN_STAFF)
def pipeline():
    """Kanban del pipeline de oportunidades, agrupado por etapa."""
    filtro_asignado = request.args.get('asignado', '')
    with get_db_cursor(dict_cursor=True) as cur:
        sql = """
            SELECT o.*, c.nombre AS contacto_nombre, c.tipo AS contacto_tipo,
                   u.nombre AS asignado_nombre
              FROM crm_oportunidades o
              JOIN crm_contactos c ON o.contacto_id = c.id
              LEFT JOIN usuarios u ON o.asignado_a = u.id
             WHERE 1=1
        """
        params = []
        if filtro_asignado and filtro_asignado.isdigit():
            sql += " AND o.asignado_a = %s"
            params.append(int(filtro_asignado))
        sql += " ORDER BY o.updated_at DESC"
        cur.execute(sql, tuple(params))
        oportunidades = cur.fetchall()

        cur.execute("SELECT id, nombre FROM usuarios WHERE estado='habilitado' ORDER BY nombre")
        usuarios = cur.fetchall()

    columnas = {e[0]: {'label': e[1], 'items': [], 'total': 0} for e in ETAPAS_OPORTUNIDAD}
    for o in oportunidades:
        col = columnas.get(o['etapa'])
        if col is not None:
            col['items'].append(o)
            col['total'] += float(o['monto_estimado'] or 0)

    return render_template(
        'crm_pipeline.html',
        etapas=ETAPAS_OPORTUNIDAD,
        columnas=columnas,
        usuarios=usuarios,
        filtro_asignado=filtro_asignado,
    )


@crm_bp.route('/oportunidades/crear', methods=['GET', 'POST'])
@crm_bp.route('/contactos/<int:contacto_id>/oportunidades/crear', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
def oportunidad_crear(contacto_id=None):
    if request.method == 'POST':
        titulo = (request.form.get('titulo') or '').strip()[:200]
        contacto_id_form = request.form.get('contacto_id')
        try:
            c_id = int(contacto_id_form) if contacto_id_form else contacto_id
        except (TypeError, ValueError):
            c_id = contacto_id
        monto = float(request.form.get('monto_estimado') or 0)
        prob = int(request.form.get('probabilidad') or 50)
        etapa = request.form.get('etapa') or 'prospecto'
        asignado_a = request.form.get('asignado_a') or None
        fecha_cierre_est = request.form.get('fecha_cierre_est') or None
        descripcion = (request.form.get('descripcion') or '').strip() or None
        fuente = request.form.get('fuente') or None

        if not titulo or not c_id:
            flash('Título y contacto son obligatorios.', 'warning')
            return redirect(url_for('crm.oportunidad_crear'))
        try:
            with get_db_cursor(dict_cursor=True) as cur:
                cur.execute("""
                    INSERT INTO crm_oportunidades
                        (contacto_id, titulo, descripcion, monto_estimado, probabilidad,
                         etapa, fuente, asignado_a, fecha_cierre_est)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id
                """, (c_id, titulo, descripcion, monto, prob, etapa, fuente,
                      asignado_a, fecha_cierre_est))
                new_id = cur.fetchone()['id']
            flash('Oportunidad creada.', 'success')
            return redirect(url_for('crm.oportunidad_editar', id=new_id))
        except Exception as e:
            app.logger.error(f"Error creando oportunidad: {e}")
            flash('Error al crear oportunidad.', 'danger')

    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT id, nombre, empresa FROM crm_contactos
             WHERE activo = TRUE ORDER BY nombre
        """)
        contactos = cur.fetchall()
        cur.execute("SELECT id, nombre FROM usuarios WHERE estado='habilitado' ORDER BY nombre")
        usuarios = cur.fetchall()
        preselect = None
        if contacto_id:
            cur.execute("SELECT id, nombre FROM crm_contactos WHERE id=%s", (contacto_id,))
            preselect = cur.fetchone()

    return render_template(
        'crm_oportunidad_form.html', modo='crear', oportunidad=None,
        contactos=contactos, usuarios=usuarios, etapas=ETAPAS_OPORTUNIDAD,
        preselect_contacto=preselect,
    )


@crm_bp.route('/oportunidades/<int:id>/editar', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
def oportunidad_editar(id):
    if request.method == 'POST':
        titulo = (request.form.get('titulo') or '').strip()[:200]
        monto = float(request.form.get('monto_estimado') or 0)
        prob = int(request.form.get('probabilidad') or 50)
        etapa = request.form.get('etapa') or 'prospecto'
        asignado_a = request.form.get('asignado_a') or None
        fecha_cierre_est = request.form.get('fecha_cierre_est') or None
        descripcion = (request.form.get('descripcion') or '').strip() or None
        motivo_perdida = (request.form.get('motivo_perdida') or '').strip()[:160] or None
        fuente = request.form.get('fuente') or None
        try:
            with get_db_cursor() as cur:
                sets = ['titulo=%s','descripcion=%s','monto_estimado=%s','probabilidad=%s',
                        'etapa=%s','fuente=%s','asignado_a=%s','fecha_cierre_est=%s',
                        'motivo_perdida=%s','updated_at=NOW()']
                vals = [titulo, descripcion, monto, prob, etapa, fuente,
                        asignado_a, fecha_cierre_est, motivo_perdida]
                if etapa in ('ganada','perdida'):
                    sets.append('fecha_cierre_real=COALESCE(fecha_cierre_real, CURRENT_DATE)')
                vals.append(id)
                cur.execute(
                    f"UPDATE crm_oportunidades SET {', '.join(sets)} WHERE id=%s",
                    tuple(vals),
                )
            flash('Oportunidad actualizada.', 'success')
        except Exception as e:
            app.logger.error(f"Error editando oportunidad {id}: {e}")
            flash('Error al actualizar.', 'danger')
        return redirect(url_for('crm.oportunidad_editar', id=id))

    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT o.*, c.nombre AS contacto_nombre
              FROM crm_oportunidades o
              JOIN crm_contactos c ON o.contacto_id = c.id
             WHERE o.id = %s
        """, (id,))
        op = cur.fetchone()
        if not op:
            flash('Oportunidad no encontrada.', 'warning')
            return redirect(url_for('crm.pipeline'))
        cur.execute("""
            SELECT id, nombre, empresa FROM crm_contactos
             WHERE activo = TRUE ORDER BY nombre
        """)
        contactos = cur.fetchall()
        cur.execute("SELECT id, nombre FROM usuarios WHERE estado='habilitado' ORDER BY nombre")
        usuarios = cur.fetchall()

    return render_template(
        'crm_oportunidad_form.html', modo='editar', oportunidad=op,
        contactos=contactos, usuarios=usuarios, etapas=ETAPAS_OPORTUNIDAD,
        preselect_contacto=None,
    )


@crm_bp.route('/oportunidades/<int:id>/etapa', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def oportunidad_cambiar_etapa(id):
    """AJAX: drag&drop del Kanban."""
    from flask import jsonify
    nueva = request.json.get('etapa') if request.is_json else request.form.get('etapa')
    validas = [e[0] for e in ETAPAS_OPORTUNIDAD]
    if nueva not in validas:
        return jsonify({'ok': False, 'error': 'etapa inválida'}), 400
    try:
        with get_db_cursor() as cur:
            sets = 'etapa=%s, updated_at=NOW()'
            params = [nueva]
            if nueva in ('ganada','perdida'):
                sets += ', fecha_cierre_real=COALESCE(fecha_cierre_real, CURRENT_DATE)'
            if nueva == 'ganada':
                sets += ', probabilidad=100'
            if nueva == 'perdida':
                sets += ', probabilidad=0'
            params.append(id)
            cur.execute(f"UPDATE crm_oportunidades SET {sets} WHERE id=%s", tuple(params))
        return jsonify({'ok': True})
    except Exception as e:
        app.logger.warning(f"oportunidad_cambiar_etapa: {e}")
        return jsonify({'ok': False, 'error': 'db error'}), 500


@crm_bp.route('/oportunidades/<int:id>/eliminar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def oportunidad_eliminar(id):
    contacto_id = request.form.get('contacto_id')
    try:
        with get_db_cursor() as cur:
            cur.execute("DELETE FROM crm_oportunidades WHERE id=%s", (id,))
        flash('Oportunidad eliminada.', 'success')
    except Exception as e:
        app.logger.error(f"Error eliminando oportunidad {id}: {e}")
        flash('Error al eliminar.', 'danger')
    if contacto_id:
        return redirect(url_for('crm.crm_contacto_ver', id=contacto_id))
    return redirect(url_for('crm.pipeline'))


# ==================================================================
# F4 — EXPORT / IMPORT CSV
# ==================================================================

@crm_bp.route('/contactos/exportar')
@rol_requerido(ADMIN_STAFF)
def contactos_exportar():
    import csv, io
    from flask import Response as _Response
    tipo_filtro = request.args.get('tipo') or None
    tag_filtro = request.args.get('tag') or None
    with get_db_cursor(dict_cursor=True) as cur:
        sql = "SELECT * FROM crm_contactos WHERE activo = TRUE"
        params = []
        if tipo_filtro:
            sql += " AND tipo = %s"; params.append(tipo_filtro)
        if tag_filtro:
            sql += " AND %s = ANY(tags)"; params.append(tag_filtro)
        sql += " ORDER BY nombre"
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['tipo','nombre','empresa','cargo','email','telefono','whatsapp',
                'ciudad','direccion','origen','tags','notas','created_at'])
    for r in rows:
        w.writerow([
            r.get('tipo') or '', r.get('nombre') or '', r.get('empresa') or '',
            r.get('cargo') or '', r.get('email') or '', r.get('telefono') or '',
            r.get('whatsapp') or '', r.get('ciudad') or '', r.get('direccion') or '',
            r.get('origen') or '', ';'.join(r.get('tags') or []),
            (r.get('notas') or '').replace('\n',' '),
            r.get('created_at').isoformat() if r.get('created_at') else '',
        ])
    return _Response(
        buf.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=crm_contactos.csv'},
    )


@crm_bp.route('/contactos/importar', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
def contactos_importar():
    if request.method == 'POST':
        import csv, io
        file = request.files.get('csv_file')
        if not file or not file.filename:
            flash('Selecciona un archivo CSV.', 'warning')
            return redirect(url_for('crm.contactos_importar'))
        try:
            content = file.read().decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(content))
            from services.crm_service import upsert_contacto
            ok = 0
            for row in reader:
                tags = [t.strip() for t in (row.get('tags') or '').split(';') if t.strip()]
                upsert_contacto(
                    email=row.get('email') or None,
                    nombre=row.get('nombre') or None,
                    telefono=row.get('telefono') or None,
                    empresa=row.get('empresa') or None,
                    ciudad=row.get('ciudad') or None,
                    direccion=row.get('direccion') or None,
                    tipo=(row.get('tipo') or 'lead').strip().lower() or 'lead',
                    origen=(row.get('origen') or 'csv_import'),
                    notas_append=row.get('notas') or None,
                    tags_add=tags + ['importado'],
                )
                ok += 1
            flash(f'Importación completada: {ok} filas procesadas.', 'success')
            return redirect(url_for('crm.crm_contactos_lista'))
        except Exception as e:
            app.logger.error(f"Error importando CSV: {e}")
            flash(f'Error procesando CSV: {e}', 'danger')
    return render_template('crm_importar.html')


# ==================================================================
# F5 — EMAIL MASIVO
# ==================================================================

@crm_bp.route('/email-masivo', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
def email_masivo():
    if request.method == 'POST':
        ids_raw = request.form.get('contactos_ids', '').strip()
        asunto = (request.form.get('asunto') or '').strip()[:200]
        cuerpo = (request.form.get('cuerpo') or '').strip()
        if not asunto or not cuerpo or not ids_raw:
            flash('Faltan datos obligatorios.', 'warning')
            return redirect(url_for('crm.email_masivo'))
        try:
            ids = [int(x) for x in ids_raw.split(',') if x.strip().isdigit()]
        except ValueError:
            ids = []
        if not ids:
            flash('No hay destinatarios.', 'warning')
            return redirect(url_for('crm.email_masivo'))
        enviados = 0
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(
                "SELECT id, nombre, email FROM crm_contactos WHERE id = ANY(%s) AND email IS NOT NULL AND email <> ''",
                (ids,),
            )
            destinatarios = cur.fetchall()
        from helpers_gmail import enviar_email_gmail
        from services.crm_service import registrar_actividad
        for d in destinatarios:
            personalizado = cuerpo.replace('{nombre}', d['nombre'] or '')
            html = f"<div style='font-family:sans-serif;max-width:600px;padding:20px;'>{personalizado.replace(chr(10),'<br>')}</div>"
            if enviar_email_gmail(d['email'], asunto, personalizado, html=html):
                enviados += 1
                registrar_actividad(
                    contacto_id=d['id'], tipo='email_masivo',
                    asunto=asunto, descripcion=cuerpo[:1000],
                    usuario_id=session.get('usuario_id'),
                )
        flash(f'Email enviado a {enviados} de {len(destinatarios)} contactos.', 'success')
        return redirect(url_for('crm.crm_contactos_lista'))

    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT id, tipo, nombre, email, empresa, tags
              FROM crm_contactos
             WHERE activo=TRUE AND email IS NOT NULL AND email <> ''
             ORDER BY nombre
        """)
        contactos = cur.fetchall()
    return render_template('crm_email_masivo.html', contactos=contactos)


# ==================================================================
# F3.3 — REGISTRO RÁPIDO DE LLAMADA (AJAX)
# ==================================================================

@crm_bp.route('/contactos/<int:id>/llamada-rapida', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def llamada_rapida(id):
    from flask import jsonify
    asunto = (request.form.get('asunto') or 'Llamada').strip()[:200]
    duracion = (request.form.get('duracion') or '').strip()
    descripcion = f"Duración: {duracion} min" if duracion else None
    try:
        from services.crm_service import registrar_actividad
        registrar_actividad(
            contacto_id=id, tipo='llamada', asunto=asunto,
            descripcion=descripcion, usuario_id=session.get('usuario_id'),
        )
        return jsonify({'ok': True})
    except Exception as e:
        app.logger.warning(f"llamada_rapida: {e}")
        return jsonify({'ok': False}), 500
