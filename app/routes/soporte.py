"""
routes/soporte.py — Módulo de tickets de soporte cliente ↔ vendedor.

MIGRACIÓN A NUEVO CLIENTE — ejecutar SQL antes de activar este módulo:

    CREATE TABLE IF NOT EXISTS tickets_soporte (
        id           SERIAL PRIMARY KEY,
        usuario_id   INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
        asunto       VARCHAR(200) NOT NULL,
        mensaje      TEXT NOT NULL,
        estado       VARCHAR(20) NOT NULL DEFAULT 'abierto',
        created_at   TIMESTAMP DEFAULT NOW(),
        updated_at   TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS ticket_respuestas (
        id         SERIAL PRIMARY KEY,
        ticket_id  INTEGER NOT NULL REFERENCES tickets_soporte(id) ON DELETE CASCADE,
        usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
        mensaje    TEXT NOT NULL,
        es_admin   BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT NOW()
    );

    -- Habilitar/deshabilitar el módulo desde admin → Soporte → Configuración.
    -- Por defecto queda habilitado (soporte_habilitado = 'true').

Parametrizable vía tabla cliente_config (grupo='soporte'):
  soporte_habilitado        → 'true'/'false'  (activa/desactiva el módulo)
  soporte_limite_semana     → número entero    (tickets activos por cliente por semana)
  soporte_auto_cierre_dias  → número entero    (días inactivo antes de auto-cierre; 0=desactivado)
  soporte_email_vendedor    → 'true'/'false'   (notificar al vendedor por email)
  soporte_email_cliente     → 'true'/'false'   (notificar al cliente por email)
  contacto_email_destino    → dirección email  (a quién llegan los tickets)
"""

from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, current_app as app)
from helpers_gmail import enviar_email_gmail

from database import get_db_cursor
from helpers import get_data_app, get_data_cliente
from security import rol_requerido, ADMIN_STAFF
from tenant_features import MODULE_SUPPORT, is_module_active, set_module_state

soporte_bp = Blueprint('soporte', __name__)


# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────

_DEFAULTS = {
    'soporte_habilitado':       'true',
    'soporte_limite_semana':    '1',
    'soporte_auto_cierre_dias': '0',
    'soporte_email_vendedor':   'true',
    'soporte_email_cliente':    'true',
    'contacto_email_destino':   '',
}


def _get_config():
    """Lee la configuración del módulo desde cliente_config con valores por defecto."""
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
    cfg['soporte_habilitado'] = 'true' if is_module_active(MODULE_SUPPORT) else 'false'
    return cfg


def _email_destino(cfg):
    return (cfg.get('contacto_email_destino') or
            app.config.get('MAIL_DEFAULT_SENDER') or
            app.config.get('MAIL_USERNAME'))


def _enviar_email(destinatario, asunto, cuerpo):
    if not enviar_email_gmail(destinatario, asunto, cuerpo):
        app.logger.warning(f"Email soporte no enviado a {destinatario}")


def _auto_cerrar(cfg):
    """Cierra tickets inactivos según soporte_auto_cierre_dias."""
    try:
        dias = int(cfg.get('soporte_auto_cierre_dias') or 0)
    except (ValueError, TypeError):
        dias = 0
    if dias <= 0:
        return
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                UPDATE tickets_soporte
                SET estado = 'cerrado', fecha_actualizado = NOW()
                WHERE estado IN ('abierto', 'respondido')
                  AND fecha_actualizado < NOW() - INTERVAL '1 day' * %s
            """, (dias,))
    except Exception as e:
        app.logger.warning(f"Auto-cierre de tickets falló: {e}")


def _count_open_tickets():
    """Retorna el número de tickets abiertos (para badge del menú)."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM tickets_soporte WHERE estado = 'abierto'"
            )
            return cur.fetchone()['cnt']
    except Exception:
        return 0


# ──────────────────────────────────────────────
# RUTAS CLIENTE
# ──────────────────────────────────────────────

@soporte_bp.route('/cliente/soporte')
@rol_requerido(3)
def mis_tickets():
    cfg = _get_config()
    if cfg['soporte_habilitado'] == 'false':
        flash('El módulo de soporte no está disponible en este momento.', 'warning')
        return redirect(url_for('auth.dashboard_cliente'))

    datosApp  = get_data_cliente()
    usuario_id = session['usuario_id']
    tickets    = []
    puede_crear   = True
    dias_restantes = 0

    try:
        limite = int(cfg.get('soporte_limite_semana') or 1)
    except (ValueError, TypeError):
        limite = 1

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            # Contar solo tickets activos (no cerrados) en los últimos 7 días
            cur.execute("""
                SELECT COUNT(*) AS cnt
                FROM tickets_soporte
                WHERE usuario_id = %s
                  AND fecha_creacion > NOW() - INTERVAL '7 days'
                  AND estado != 'cerrado'
            """, (usuario_id,))
            if cur.fetchone()['cnt'] >= limite:
                puede_crear = False
                # Días hasta que el ticket activo más antiguo supere los 7 días
                cur.execute("""
                    SELECT fecha_creacion FROM tickets_soporte
                    WHERE usuario_id = %s AND estado != 'cerrado'
                    ORDER BY fecha_creacion ASC LIMIT 1
                """, (usuario_id,))
                row = cur.fetchone()
                if row:
                    from datetime import datetime, timezone, timedelta
                    ahora = datetime.now(timezone.utc)
                    fc = row['fecha_creacion']
                    if fc.tzinfo is None:
                        fc = fc.replace(tzinfo=timezone.utc)
                    restante = timedelta(days=7) - (ahora - fc)
                    dias_restantes = max(1, restante.days + 1)

            # Historial completo
            cur.execute("""
                SELECT t.id, t.asunto, t.estado, t.fecha_creacion,
                       COUNT(r.id) AS num_respuestas,
                       MAX(r.fecha) AS ultima_respuesta
                FROM tickets_soporte t
                LEFT JOIN ticket_respuestas r ON r.ticket_id = t.id
                WHERE t.usuario_id = %s
                GROUP BY t.id
                ORDER BY t.fecha_creacion DESC
            """, (usuario_id,))
            tickets = cur.fetchall()
    except Exception as e:
        app.logger.error(f"Error cargando tickets: {e}")

    return render_template('mis_tickets.html', datosApp=datosApp,
                           tickets=tickets, puede_crear=puede_crear,
                           dias_restantes=dias_restantes, limite=limite)


@soporte_bp.route('/cliente/soporte/nuevo', methods=['POST'])
@rol_requerido(3)
def crear_ticket():
    cfg = _get_config()
    if cfg['soporte_habilitado'] == 'false':
        flash('El módulo de soporte no está disponible.', 'warning')
        return redirect(url_for('auth.dashboard_cliente'))

    usuario_id = session['usuario_id']
    asunto  = request.form.get('asunto', '').strip()
    mensaje = request.form.get('mensaje', '').strip()

    if not asunto or not mensaje:
        flash('El asunto y el mensaje son obligatorios.', 'error')
        return redirect(url_for('soporte.mis_tickets'))

    try:
        limite = int(cfg.get('soporte_limite_semana') or 1)
    except (ValueError, TypeError):
        limite = 1

    ticket_id = None
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            # Verificar límite (solo tickets activos, no cerrados)
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM tickets_soporte
                WHERE usuario_id = %s
                  AND fecha_creacion > NOW() - INTERVAL '7 days'
                  AND estado != 'cerrado'
            """, (usuario_id,))
            if cur.fetchone()['cnt'] >= limite:
                flash('Límite semanal alcanzado. Espera a que tu ticket activo sea respondido o cerrado.', 'warning')
                return redirect(url_for('soporte.mis_tickets'))

            cur.execute("""
                INSERT INTO tickets_soporte (usuario_id, asunto, mensaje)
                VALUES (%s, %s, %s) RETURNING id
            """, (usuario_id, asunto, mensaje))
            ticket_id = cur.fetchone()['id']

            cur.execute("SELECT nombre, email FROM usuarios WHERE id = %s", (usuario_id,))
            cliente = cur.fetchone()

        if cfg.get('soporte_email_vendedor') != 'false':
            vendedor_email = _email_destino(cfg)
            if vendedor_email:
                _enviar_email(
                    destinatario=vendedor_email,
                    asunto=f"[Ticket #{ticket_id}] {asunto}",
                    cuerpo=(
                        f"Nuevo ticket de soporte recibido.\n\n"
                        f"Cliente: {cliente['nombre']} ({cliente['email']})\n"
                        f"Asunto: {asunto}\n\n"
                        f"Mensaje:\n{mensaje}\n\n"
                        f"Responde desde el panel admin: /admin/soporte/{ticket_id}"
                    )
                )

        flash('Tu ticket fue enviado. Te responderemos pronto.', 'success')
    except Exception as e:
        app.logger.error(f"Error creando ticket: {e}")
        flash('Error al enviar el ticket. Inténtalo de nuevo.', 'error')
        return redirect(url_for('soporte.mis_tickets'))   # ← evita NameError

    return redirect(url_for('soporte.ver_ticket_cliente', ticket_id=ticket_id))


@soporte_bp.route('/cliente/soporte/<int:ticket_id>')
@rol_requerido(3)
def ver_ticket_cliente(ticket_id):
    datosApp   = get_data_cliente()
    usuario_id = session['usuario_id']
    ticket     = None
    respuestas = []

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT * FROM tickets_soporte
                WHERE id = %s AND usuario_id = %s
            """, (ticket_id, usuario_id))
            ticket = cur.fetchone()

            if ticket:
                cur.execute("""
                    SELECT r.*, u.nombre AS autor_nombre
                    FROM ticket_respuestas r
                    JOIN usuarios u ON u.id = r.usuario_id
                    WHERE r.ticket_id = %s
                    ORDER BY r.fecha ASC
                """, (ticket_id,))
                respuestas = cur.fetchall()
    except Exception as e:
        app.logger.error(f"Error cargando ticket {ticket_id}: {e}")

    if not ticket:
        flash('Ticket no encontrado.', 'warning')
        return redirect(url_for('soporte.mis_tickets'))

    return render_template('ver_ticket.html', datosApp=datosApp,
                           ticket=ticket, respuestas=respuestas, modo_admin=False)


@soporte_bp.route('/cliente/soporte/<int:ticket_id>/responder', methods=['POST'])
@rol_requerido(3)
def cliente_responder_ticket(ticket_id):
    """El cliente replica en su propio ticket (siempre que no esté cerrado)."""
    usuario_id = session['usuario_id']
    mensaje    = request.form.get('mensaje', '').strip()

    if not mensaje:
        flash('El mensaje no puede estar vacío.', 'error')
        return redirect(url_for('soporte.ver_ticket_cliente', ticket_id=ticket_id))

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            # Seguridad: el ticket debe pertenecer al cliente y no estar cerrado
            cur.execute("""
                SELECT id, asunto FROM tickets_soporte
                WHERE id = %s AND usuario_id = %s AND estado != 'cerrado'
            """, (ticket_id, usuario_id))
            ticket = cur.fetchone()
            if not ticket:
                flash('No puedes responder a este ticket.', 'warning')
                return redirect(url_for('soporte.mis_tickets'))

            cur.execute("""
                INSERT INTO ticket_respuestas (ticket_id, usuario_id, mensaje, es_admin)
                VALUES (%s, %s, %s, FALSE)
            """, (ticket_id, usuario_id, mensaje))

            # Vuelve a "abierto" para que el admin lo atienda
            cur.execute("""
                UPDATE tickets_soporte
                SET estado = 'abierto', fecha_actualizado = NOW()
                WHERE id = %s
            """, (ticket_id,))

        # Notificar al vendedor
        cfg = _get_config()
        if cfg.get('soporte_email_vendedor') != 'false':
            vendedor_email = _email_destino(cfg)
            if vendedor_email:
                _enviar_email(
                    destinatario=vendedor_email,
                    asunto=f"[Seguimiento Ticket #{ticket_id}] {ticket['asunto']}",
                    cuerpo=(
                        f"El cliente ha añadido un mensaje al ticket #{ticket_id}.\n\n"
                        f"Mensaje:\n{mensaje}\n\n"
                        f"Ver ticket: /admin/soporte/{ticket_id}"
                    )
                )

        flash('Mensaje enviado.', 'success')
    except Exception as e:
        app.logger.error(f"Error al responder ticket {ticket_id}: {e}")
        flash('Error al enviar el mensaje.', 'error')

    return redirect(url_for('soporte.ver_ticket_cliente', ticket_id=ticket_id))


@soporte_bp.route('/cliente/soporte/<int:ticket_id>/resolver', methods=['POST'])
@rol_requerido(3)
def cliente_cerrar_ticket(ticket_id):
    """El cliente marca su ticket como resuelto."""
    usuario_id = session['usuario_id']
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                UPDATE tickets_soporte SET estado = 'cerrado', fecha_actualizado = NOW()
                WHERE id = %s AND usuario_id = %s AND estado != 'cerrado'
            """, (ticket_id, usuario_id))
        flash('Ticket marcado como resuelto. Ahora puedes abrir uno nuevo.', 'success')
    except Exception as e:
        app.logger.error(f"Error cerrando ticket {ticket_id}: {e}")
        flash('Error al cerrar el ticket.', 'error')
    return redirect(url_for('soporte.mis_tickets'))


# ──────────────────────────────────────────────
# RUTAS ADMIN
# ──────────────────────────────────────────────

@soporte_bp.route('/admin/soporte')
@rol_requerido(ADMIN_STAFF)
def admin_tickets():
    datosApp     = get_data_app()
    estado_filtro = request.args.get('estado', 'todos')
    tickets = []
    stats   = {'abierto': 0, 'respondido': 0, 'cerrado': 0}

    cfg = _get_config()
    _auto_cerrar(cfg)   # cierre automático si está configurado

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            # Conteos por estado
            cur.execute("SELECT estado, COUNT(*) AS cnt FROM tickets_soporte GROUP BY estado")
            for r in cur.fetchall():
                stats[r['estado']] = r['cnt']

            # Lista
            sql = """
                SELECT t.id, t.asunto, t.estado, t.fecha_creacion, t.fecha_actualizado,
                       u.nombre AS cliente_nombre, u.email AS cliente_email,
                       COUNT(r.id) AS num_respuestas
                FROM tickets_soporte t
                JOIN usuarios u ON u.id = t.usuario_id
                LEFT JOIN ticket_respuestas r ON r.ticket_id = t.id
                {where}
                GROUP BY t.id, u.nombre, u.email
                ORDER BY
                    CASE t.estado WHEN 'abierto' THEN 0 WHEN 'respondido' THEN 1 ELSE 2 END,
                    t.fecha_actualizado DESC
            """
            if estado_filtro != 'todos':
                cur.execute(sql.format(where="WHERE t.estado = %s"), (estado_filtro,))
            else:
                cur.execute(sql.format(where=""))
            tickets = cur.fetchall()
    except Exception as e:
        app.logger.error(f"Error cargando tickets admin: {e}")

    return render_template('admin_tickets.html', datosApp=datosApp,
                           tickets=tickets, estado_filtro=estado_filtro, stats=stats)


@soporte_bp.route('/admin/soporte/<int:ticket_id>')
@rol_requerido(ADMIN_STAFF)
def admin_ver_ticket(ticket_id):
    datosApp   = get_data_app()
    ticket     = None
    respuestas = []

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT t.*, u.nombre AS cliente_nombre, u.email AS cliente_email
                FROM tickets_soporte t
                JOIN usuarios u ON u.id = t.usuario_id
                WHERE t.id = %s
            """, (ticket_id,))
            ticket = cur.fetchone()

            if ticket:
                cur.execute("""
                    SELECT r.*, u.nombre AS autor_nombre
                    FROM ticket_respuestas r
                    JOIN usuarios u ON u.id = r.usuario_id
                    WHERE r.ticket_id = %s
                    ORDER BY r.fecha ASC
                """, (ticket_id,))
                respuestas = cur.fetchall()
    except Exception as e:
        app.logger.error(f"Error cargando ticket admin {ticket_id}: {e}")

    if not ticket:
        flash('Ticket no encontrado.', 'warning')
        return redirect(url_for('soporte.admin_tickets'))

    return render_template('ver_ticket.html', datosApp=datosApp,
                           ticket=ticket, respuestas=respuestas, modo_admin=True)


@soporte_bp.route('/admin/soporte/<int:ticket_id>/responder', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def admin_responder_ticket(ticket_id):
    usuario_id = session['usuario_id']
    mensaje    = request.form.get('mensaje', '').strip()

    if not mensaje:
        flash('El mensaje no puede estar vacío.', 'error')
        return redirect(url_for('soporte.admin_ver_ticket', ticket_id=ticket_id))

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                INSERT INTO ticket_respuestas (ticket_id, usuario_id, mensaje, es_admin)
                VALUES (%s, %s, %s, TRUE)
            """, (ticket_id, usuario_id, mensaje))

            cur.execute("""
                UPDATE tickets_soporte
                SET estado = 'respondido', fecha_actualizado = NOW()
                WHERE id = %s
            """, (ticket_id,))

            cur.execute("""
                SELECT u.nombre, u.email, t.asunto
                FROM tickets_soporte t
                JOIN usuarios u ON u.id = t.usuario_id
                WHERE t.id = %s
            """, (ticket_id,))
            datos = cur.fetchone()

        cfg = _get_config()
        if datos and cfg.get('soporte_email_cliente') != 'false':
            _enviar_email(
                destinatario=datos['email'],
                asunto=f"Re: [Ticket #{ticket_id}] {datos['asunto']}",
                cuerpo=(
                    f"Hola {datos['nombre']},\n\n"
                    f"Hemos respondido a tu ticket #{ticket_id}:\n\n"
                    f"{mensaje}\n\n"
                    f"Puedes ver la conversación completa y continuar respondiendo desde tu cuenta."
                )
            )

        flash('Respuesta enviada al cliente.', 'success')
    except Exception as e:
        app.logger.error(f"Error respondiendo ticket {ticket_id}: {e}")
        flash(f'Error al responder: {e}', 'error')

    return redirect(url_for('soporte.admin_ver_ticket', ticket_id=ticket_id))


@soporte_bp.route('/admin/soporte/<int:ticket_id>/cerrar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def admin_cerrar_ticket(ticket_id):
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                UPDATE tickets_soporte SET estado = 'cerrado', fecha_actualizado = NOW()
                WHERE id = %s
            """, (ticket_id,))
        flash('Ticket cerrado.', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'danger')
    return redirect(url_for('soporte.admin_tickets'))


@soporte_bp.route('/admin/soporte/<int:ticket_id>/reabrir', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def admin_reabrir_ticket(ticket_id):
    """Reabre un ticket cerrado para continuar la conversación."""
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                UPDATE tickets_soporte SET estado = 'abierto', fecha_actualizado = NOW()
                WHERE id = %s
            """, (ticket_id,))
        flash('Ticket reabierto.', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'danger')
    return redirect(url_for('soporte.admin_ver_ticket', ticket_id=ticket_id))


# ──────────────────────────────────────────────
# CONFIG ADMIN
# ──────────────────────────────────────────────

@soporte_bp.route('/admin/soporte/configuracion', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
def admin_soporte_config():
    """Página de configuración parametrizable del módulo de soporte."""
    datosApp = get_data_app()
    cfg = _get_config()

    if request.method == 'POST':
        module_enabled = request.form.get('soporte_habilitado', '').strip().lower() == 'true'
        campos = [
            'soporte_limite_semana',
            'soporte_auto_cierre_dias', 'soporte_email_vendedor',
            'soporte_email_cliente', 'contacto_email_destino'
        ]
        try:
            if not set_module_state(MODULE_SUPPORT, module_enabled):
                raise RuntimeError('No fue posible actualizar el estado del modulo de soporte.')
            with get_db_cursor() as cur:
                for clave in campos:
                    valor = request.form.get(clave, '').strip()
                    cur.execute("UPDATE cliente_config SET valor=%s WHERE clave=%s", (valor, clave))
                    if cur.rowcount == 0:
                        cur.execute(
                            "INSERT INTO cliente_config (clave, valor, tipo, grupo) VALUES (%s,%s,'text','soporte')",
                            (clave, valor)
                        )
            flash('Configuración de soporte actualizada.', 'success')
        except Exception as e:
            app.logger.error(f"Error guardando config soporte: {e}")
            flash('Error al guardar la configuración.', 'error')
        return redirect(url_for('soporte.admin_soporte_config'))

    return render_template('admin_soporte_config.html', datosApp=datosApp, cfg=cfg)
