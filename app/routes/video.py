"""
routes/video.py — Modulo de videollamadas con Jitsi Meet.

Permite crear salas de videoconferencia, invitar participantes por email
y unirse a reuniones desde el navegador con camara, microfono y pantalla
compartida.

MIGRACION — ejecutar SQL antes de activar este modulo:

    CREATE TABLE IF NOT EXISTS salas_video ( ... );
    CREATE TABLE IF NOT EXISTS sala_video_participantes ( ... );

    -- Ver database.sql seccion "Migracion: Modulo de Videollamadas"

Parametrizable via tabla cliente_config (grupo='video'):
  video_habilitado        -> 'true'/'false'
  video_jitsi_domain      -> dominio Jitsi (meet.jit.si por defecto)
  video_max_participantes -> numero maximo de participantes por sala
"""

import secrets
import uuid

from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, current_app as app)

from database import get_db_cursor
from helpers import get_data_app, get_data_cliente
from helpers_gmail import enviar_email_gmail
from security import rol_requerido, ADMIN_STAFF, ROLES_CLIENTE
from tenant_features import MODULE_VIDEO, is_module_active, set_module_state

video_bp = Blueprint('video', __name__)


# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------

_DEFAULTS = {
    'video_habilitado':        'true',
    'video_jitsi_domain':      'meet.jit.si',
    'video_max_participantes': '10',
}


def _get_config():
    cfg = dict(_DEFAULTS)
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(
                "SELECT clave, valor FROM cliente_config WHERE clave = ANY(%s)",
                (list(_DEFAULTS.keys()),)
            )
            for row in cur.fetchall():
                if row['valor'] is not None:
                    cfg[row['clave']] = row['valor']
    except Exception:
        pass
    cfg['video_habilitado'] = 'true' if is_module_active(MODULE_VIDEO) else 'false'
    return cfg


def _generar_codigo_sala():
    return f"cs-{uuid.uuid4().hex[:12]}"


def _generar_token():
    return secrets.token_urlsafe(48)


def _enviar_invitacion(destinatario, nombre_participante, sala, token):
    """Envia email de invitacion con link de acceso a la sala."""
    join_url = url_for('video.unirse_sala', token=token, _external=True)

    cuerpo = (
        f"Hola {nombre_participante},\n\n"
        f"Has sido invitado a una videollamada: {sala['nombre']}\n\n"
        f"Unete aqui: {join_url}\n\n"
        f"No necesitas instalar nada. Funciona desde tu navegador.\n"
        f"Nota: necesitas tener una cuenta registrada para unirte."
    )

    cuerpo_html = f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:600px;margin:0 auto;
                border:1px solid #e0e0e0;border-radius:12px;overflow:hidden;">
        <div style="background:linear-gradient(135deg,var(--color-primario,#122C94),var(--color-primario-oscuro,#091C5A));
                    padding:24px 30px;">
            <h2 style="color:#fff;margin:0;font-size:20px;">
                &#128249; Invitacion a videollamada
            </h2>
        </div>
        <div style="padding:28px 30px;background:#fff;">
            <p>Hola <strong>{nombre_participante}</strong>,</p>
            <p>Has sido invitado a una videollamada:</p>
            <h3 style="color:#122C94;">{sala['nombre']}</h3>
            {f'<p>{sala["descripcion"]}</p>' if sala.get('descripcion') else ''}
            <p style="text-align:center;margin:24px 0;">
                <a href="{join_url}"
                   style="background:#122C94;color:#fff;padding:14px 32px;
                          border-radius:8px;text-decoration:none;font-weight:600;
                          font-size:1.05em;display:inline-block;">
                    Unirse a la reunion
                </a>
            </p>
            <p style="color:#888;font-size:0.9em;">
                No necesitas instalar nada. Funciona desde tu navegador.<br>
                Necesitas tener una cuenta registrada para unirte.
            </p>
        </div>
    </div>"""

    if not enviar_email_gmail(destinatario, f"Invitacion: {sala['nombre']}", cuerpo, html=cuerpo_html):
        app.logger.warning(f"Email video no enviado a {destinatario}")


# ------------------------------------------------------------------
# RUTAS ADMIN
# ------------------------------------------------------------------

@video_bp.route('/admin/video')
@rol_requerido(ADMIN_STAFF)
def admin_video_lista():
    cfg = _get_config()
    if cfg['video_habilitado'] == 'false':
        flash('El modulo de videollamadas no esta habilitado.', 'warning')
        return redirect(url_for('admin.dashboard_admin'))

    datosApp = get_data_app()
    salas = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT s.*, u.nombre AS creador_nombre,
                       (SELECT COUNT(*) FROM sala_video_participantes
                        WHERE sala_id = s.id) AS num_participantes
                FROM salas_video s
                LEFT JOIN usuarios u ON u.id = s.creado_por
                ORDER BY s.created_at DESC
            """)
            salas = cur.fetchall()
    except Exception as e:
        app.logger.error(f"Error cargando salas: {e}")

    return render_template('video_lista.html', datosApp=datosApp, salas=salas)


@video_bp.route('/admin/video/nueva', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
def admin_video_crear():
    cfg = _get_config()
    if cfg['video_habilitado'] == 'false':
        flash('El modulo de videollamadas no esta habilitado.', 'warning')
        return redirect(url_for('admin.dashboard_admin'))

    datosApp = get_data_app()

    if request.method == 'POST':
        nombre      = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        fecha_inicio = request.form.get('fecha_inicio', '').strip() or None
        password_sala = request.form.get('password_sala', '').strip() or None

        if not nombre:
            flash('El nombre de la sala es obligatorio.', 'error')
            return render_template('video_crear.html', datosApp=datosApp)

        try:
            max_part = int(cfg.get('video_max_participantes', 10))
        except (ValueError, TypeError):
            max_part = 10

        codigo = _generar_codigo_sala()
        usuario_id = session['usuario_id']

        try:
            with get_db_cursor(dict_cursor=True) as cur:
                cur.execute("""
                    INSERT INTO salas_video
                        (codigo_sala, nombre, descripcion, creado_por,
                         fecha_inicio, max_participantes, password_sala)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (codigo, nombre, descripcion, usuario_id,
                      fecha_inicio, max_part, password_sala))
                sala_id = cur.fetchone()['id']

                # Agregar al creador como moderador
                token_creador = _generar_token()
                cur.execute("""
                    INSERT INTO sala_video_participantes
                        (sala_id, usuario_id, email, nombre, token_acceso, rol_sala)
                    VALUES (%s, %s, %s, %s, %s, 'moderador')
                """, (sala_id, usuario_id, session.get('email'),
                      session.get('username'), token_creador))

            flash('Sala creada exitosamente.', 'success')
            return redirect(url_for('video.admin_video_detalle', id=sala_id))
        except Exception as e:
            app.logger.error(f"Error creando sala: {e}")
            flash('Error al crear la sala.', 'error')

    return render_template('video_crear.html', datosApp=datosApp)


@video_bp.route('/admin/video/<int:id>')
@rol_requerido(ADMIN_STAFF)
def admin_video_detalle(id):
    datosApp = get_data_app()
    sala = None
    participantes = []

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT s.*, u.nombre AS creador_nombre
                FROM salas_video s
                LEFT JOIN usuarios u ON u.id = s.creado_por
                WHERE s.id = %s
            """, (id,))
            sala = cur.fetchone()

            if sala:
                cur.execute("""
                    SELECT p.*, u.nombre AS usuario_nombre
                    FROM sala_video_participantes p
                    LEFT JOIN usuarios u ON u.id = p.usuario_id
                    WHERE p.sala_id = %s
                    ORDER BY p.created_at
                """, (id,))
                participantes = cur.fetchall()
    except Exception as e:
        app.logger.error(f"Error cargando sala {id}: {e}")

    if not sala:
        flash('Sala no encontrada.', 'warning')
        return redirect(url_for('video.admin_video_lista'))

    return render_template('video_detalle.html', datosApp=datosApp,
                           sala=sala, participantes=participantes)


@video_bp.route('/admin/video/<int:id>/invitar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def admin_video_invitar(id):
    emails_raw = request.form.get('emails', '').strip()
    if not emails_raw:
        flash('Ingresa al menos un email.', 'error')
        return redirect(url_for('video.admin_video_detalle', id=id))

    emails = [e.strip() for e in emails_raw.replace('\n', ',').split(',') if e.strip()]

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT * FROM salas_video WHERE id = %s", (id,))
            sala = cur.fetchone()
            if not sala:
                flash('Sala no encontrada.', 'warning')
                return redirect(url_for('video.admin_video_lista'))

            for email in emails:
                # Verificar si ya esta invitado
                cur.execute("""
                    SELECT id FROM sala_video_participantes
                    WHERE sala_id = %s AND email = %s
                """, (id, email))
                if cur.fetchone():
                    continue

                # Buscar si tiene cuenta
                cur.execute("SELECT id, nombre FROM usuarios WHERE email = %s", (email,))
                usuario = cur.fetchone()

                token = _generar_token()
                nombre_p = usuario['nombre'] if usuario else email.split('@')[0]

                cur.execute("""
                    INSERT INTO sala_video_participantes
                        (sala_id, usuario_id, email, nombre, token_acceso, invitado)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (id, usuario['id'] if usuario else None, email,
                      nombre_p, token, not bool(usuario)))

                # Enviar email
                _enviar_invitacion(email, nombre_p, sala, token)

                cur.execute("""
                    UPDATE sala_video_participantes
                    SET email_enviado = TRUE
                    WHERE sala_id = %s AND email = %s
                """, (id, email))

        flash(f'{len(emails)} invitacion(es) enviada(s).', 'success')
    except Exception as e:
        app.logger.error(f"Error invitando participantes: {e}")
        flash('Error al enviar invitaciones.', 'error')

    return redirect(url_for('video.admin_video_detalle', id=id))


@video_bp.route('/admin/video/<int:id>/iniciar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def admin_video_iniciar(id):
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                UPDATE salas_video SET estado = 'activa', updated_at = NOW()
                WHERE id = %s AND estado IN ('programada')
            """, (id,))
    except Exception as e:
        app.logger.error(f"Error iniciando sala {id}: {e}")
        flash('Error al iniciar la sala.', 'error')
        return redirect(url_for('video.admin_video_detalle', id=id))

    flash('Sala iniciada.', 'success')
    return redirect(url_for('video.admin_video_detalle', id=id))


@video_bp.route('/admin/video/<int:id>/finalizar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def admin_video_finalizar(id):
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                UPDATE salas_video
                SET estado = 'finalizada', fecha_fin = NOW(), updated_at = NOW()
                WHERE id = %s AND estado = 'activa'
            """, (id,))
    except Exception as e:
        app.logger.error(f"Error finalizando sala {id}: {e}")
        flash('Error al finalizar la sala.', 'error')
        return redirect(url_for('video.admin_video_detalle', id=id))

    flash('Sala finalizada.', 'success')
    return redirect(url_for('video.admin_video_detalle', id=id))


@video_bp.route('/admin/video/<int:id>/cancelar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def admin_video_cancelar(id):
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                UPDATE salas_video
                SET estado = 'cancelada', updated_at = NOW()
                WHERE id = %s AND estado IN ('programada', 'activa')
            """, (id,))
    except Exception as e:
        app.logger.error(f"Error cancelando sala {id}: {e}")
        flash('Error al cancelar la sala.', 'error')
        return redirect(url_for('video.admin_video_detalle', id=id))

    flash('Sala cancelada.', 'success')
    return redirect(url_for('video.admin_video_detalle', id=id))


# ------------------------------------------------------------------
# RUTA PUBLICA: UNIRSE A SALA (requiere autenticacion)
# ------------------------------------------------------------------

@video_bp.route('/sala/<token>')
def unirse_sala(token):
    """Pagina de videollamada. Requiere usuario autenticado."""
    cfg = _get_config()

    # Buscar participante por token
    participante = None
    sala = None
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT p.*, s.codigo_sala, s.nombre, s.descripcion,
                       s.estado, s.password_sala, s.max_participantes
                FROM sala_video_participantes p
                JOIN salas_video s ON s.id = p.sala_id
                WHERE p.token_acceso = %s
            """, (token,))
            participante = cur.fetchone()
    except Exception as e:
        app.logger.error(f"Error buscando token de sala: {e}")

    if not participante:
        flash('Enlace de reunion no valido o expirado.', 'error')
        return redirect(url_for('public.index'))

    sala = {
        'codigo_sala': participante['codigo_sala'],
        'nombre': participante['nombre_1'] if 'nombre_1' in participante else participante['nombre'],
        'descripcion': participante['descripcion'],
        'estado': participante['estado'],
        'password_sala': participante['password_sala'],
    }
    # Fix: la query retorna nombre de la sala y del participante con alias
    # Re-query para claridad
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT * FROM salas_video WHERE id = %s", (participante['sala_id'],))
            sala_row = cur.fetchone()
            if sala_row:
                sala = sala_row
    except Exception:
        pass

    # Validar estado de la sala
    if sala['estado'] not in ('programada', 'activa'):
        flash('Esta reunion ya ha finalizado o fue cancelada.', 'warning')
        return redirect(url_for('public.index'))

    # Verificar autenticacion
    if not session.get('usuario_id'):
        session['login_next'] = url_for('video.unirse_sala', token=token)
        flash('Inicia sesion o registrate para unirte a la videollamada.', 'info')
        return redirect(url_for('auth.login'))

    # Verificar que el usuario logueado corresponde al participante
    usuario_id = session['usuario_id']
    email_usuario = session.get('email', '')

    # Si el participante tiene usuario_id, debe coincidir
    # Si no tiene (invitado externo), vincular por email
    acceso_valido = False
    if participante['usuario_id']:
        acceso_valido = (participante['usuario_id'] == usuario_id)
    elif participante['email'] and participante['email'].lower() == email_usuario.lower():
        acceso_valido = True
        # Vincular usuario_id ahora que se registro
        try:
            with get_db_cursor() as cur:
                cur.execute("""
                    UPDATE sala_video_participantes
                    SET usuario_id = %s WHERE id = %s
                """, (usuario_id, participante['id']))
        except Exception:
            pass

    if not acceso_valido:
        flash('No tienes acceso a esta reunion.', 'error')
        return redirect(url_for('public.index'))

    # Marcar como unido
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                UPDATE sala_video_participantes
                SET se_unio = TRUE, fecha_union = COALESCE(fecha_union, NOW())
                WHERE id = %s
            """, (participante['id'],))
    except Exception:
        pass

    nombre_usuario = session.get('username', '')
    es_moderador = participante['rol_sala'] == 'moderador'

    # Determinar template base segun rol
    rol_id = session.get('rol_id')
    if rol_id in ADMIN_STAFF:
        datosApp = get_data_app()
        base_template = 'plantillaapp.html'
    else:
        datosApp = get_data_cliente()
        base_template = 'plantillaapp.html'

    return render_template('video_sala.html',
                           datosApp=datosApp,
                           base_template=base_template,
                           sala=sala,
                           token_acceso=token,
                           jitsi_domain=cfg['video_jitsi_domain'],
                           nombre_participante=nombre_usuario,
                           email_participante=email_usuario,
                           es_moderador=es_moderador)


# ------------------------------------------------------------------
# VISTA CLIENTE: MIS VIDEOLLAMADAS
# ------------------------------------------------------------------

@video_bp.route('/cliente/videollamadas')
@rol_requerido(ROLES_CLIENTE)
def mis_videollamadas():
    cfg = _get_config()
    if cfg['video_habilitado'] == 'false':
        flash('El modulo de videollamadas no esta disponible.', 'warning')
        return redirect(url_for('auth.dashboard_cliente'))

    datosApp = get_data_cliente()
    usuario_id = session['usuario_id']
    salas = []

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT s.*, p.token_acceso, p.rol_sala, p.se_unio,
                       u.nombre AS creador_nombre
                FROM sala_video_participantes p
                JOIN salas_video s ON s.id = p.sala_id
                LEFT JOIN usuarios u ON u.id = s.creado_por
                WHERE p.usuario_id = %s
                ORDER BY s.created_at DESC
            """, (usuario_id,))
            salas = cur.fetchall()
    except Exception as e:
        app.logger.error(f"Error cargando videollamadas cliente: {e}")

    return render_template('video_lista_cliente.html', datosApp=datosApp, salas=salas)


# ------------------------------------------------------------------
# CONFIGURACION ADMIN
# ------------------------------------------------------------------

@video_bp.route('/admin/video/configuracion', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
def admin_video_config():
    datosApp = get_data_app()

    if request.method == 'POST':
        module_enabled = request.form.get('video_habilitado', 'false') == 'true'
        campos = {
            'video_jitsi_domain':      request.form.get('video_jitsi_domain', 'meet.jit.si').strip(),
            'video_max_participantes': request.form.get('video_max_participantes', '10').strip(),
        }
        try:
            if not set_module_state(MODULE_VIDEO, module_enabled):
                raise RuntimeError('No fue posible actualizar el estado del modulo de videollamadas.')
            with get_db_cursor() as cur:
                for clave, valor in campos.items():
                    cur.execute("""
                        UPDATE cliente_config SET valor = %s WHERE clave = %s
                    """, (valor, clave))
                    if cur.rowcount == 0:
                        cur.execute("""
                            INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
                            VALUES (%s, %s, 'text', 'video', %s, 10)
                        """, (clave, valor, clave))
            flash('Configuracion guardada.', 'success')
        except Exception as e:
            app.logger.error(f"Error guardando config video: {e}")
            flash('Error al guardar la configuracion.', 'error')

    cfg = _get_config()
    return render_template('video_config.html', datosApp=datosApp, cfg=cfg)
