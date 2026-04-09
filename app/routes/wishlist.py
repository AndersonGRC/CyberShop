"""
routes/wishlist.py — Blueprint de lista de deseos (wishlist).

Rutas cliente: ver wishlist, toggle producto.
Rutas admin: estadisticas de productos mas deseados.
API: toggle y listar IDs para frontend.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask import current_app as app

from database import get_db_cursor
from helpers import get_data_app, get_data_cliente
from security import rol_requerido, ADMIN_STAFF, ROL_CLIENTE

wishlist_bp = Blueprint('wishlist', __name__)


# ─────────────────────────────────────────────────────────
# Pagina del cliente
# ─────────────────────────────────────────────────────────

@wishlist_bp.route('/mi-lista-deseos')
@rol_requerido(ROL_CLIENTE)
def mi_lista_deseos():
    """Muestra la lista de deseos del cliente autenticado."""
    datosApp = get_data_cliente()
    usuario_id = session.get('usuario_id')
    productos = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT p.id, p.nombre, p.precio, p.imagen, p.stock, p.referencia,
                       g.nombre AS genero,
                       ld.fecha_agregado,
                       (SELECT imagen_url FROM producto_imagenes
                        WHERE producto_id = p.id AND es_principal = TRUE LIMIT 1) AS imagen_principal
                FROM lista_deseos ld
                JOIN productos p ON ld.producto_id = p.id
                LEFT JOIN generos g ON p.genero_id = g.id
                WHERE ld.usuario_id = %s
                ORDER BY ld.fecha_agregado DESC
            """, (usuario_id,))
            productos = cur.fetchall()
    except Exception as e:
        app.logger.error(f"Error cargando wishlist: {e}")

    return render_template('lista_deseos.html', datosApp=datosApp, productos=productos)


# ─────────────────────────────────────────────────────────
# API endpoints (AJAX)
# ─────────────────────────────────────────────────────────

@wishlist_bp.route('/api/wishlist/toggle/<int:producto_id>', methods=['POST'])
def api_toggle_wishlist(producto_id):
    """Toggle: agrega o quita un producto de la wishlist."""
    usuario_id = session.get('usuario_id')
    if not usuario_id:
        return jsonify({'error': 'Debes iniciar sesión.'}), 401

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(
                "SELECT id FROM lista_deseos WHERE usuario_id = %s AND producto_id = %s",
                (usuario_id, producto_id)
            )
            existe = cur.fetchone()

            if existe:
                cur.execute(
                    "DELETE FROM lista_deseos WHERE usuario_id = %s AND producto_id = %s",
                    (usuario_id, producto_id)
                )
                return jsonify({'action': 'removed', 'producto_id': producto_id})
            else:
                cur.execute(
                    "INSERT INTO lista_deseos (usuario_id, producto_id) VALUES (%s, %s)",
                    (usuario_id, producto_id)
                )
                return jsonify({'action': 'added', 'producto_id': producto_id})
    except Exception as e:
        app.logger.error(f"Error toggle wishlist: {e}")
        return jsonify({'error': 'Error al procesar.'}), 500


@wishlist_bp.route('/api/wishlist/ids')
def api_wishlist_ids():
    """Retorna los IDs de productos en la wishlist del usuario actual."""
    usuario_id = session.get('usuario_id')
    if not usuario_id:
        return jsonify({'ids': []})

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(
                "SELECT producto_id FROM lista_deseos WHERE usuario_id = %s",
                (usuario_id,)
            )
            ids = [row['producto_id'] for row in cur.fetchall()]
        return jsonify({'ids': ids})
    except Exception:
        return jsonify({'ids': []})


# ─────────────────────────────────────────────────────────
# Admin: Estadisticas
# ─────────────────────────────────────────────────────────

@wishlist_bp.route('/admin/wishlist-estadisticas')
@rol_requerido(ADMIN_STAFF)
def wishlist_estadisticas():
    """Muestra productos mas deseados y usuarios mas activos."""
    datosApp = get_data_app()
    productos_top = []
    usuarios_top = []
    total_deseos = 0

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            # Top 20 productos más deseados
            cur.execute("""
                SELECT p.id, p.nombre, p.precio, p.imagen, p.stock,
                       COUNT(ld.id) AS deseos
                FROM lista_deseos ld
                JOIN productos p ON ld.producto_id = p.id
                GROUP BY p.id, p.nombre, p.precio, p.imagen, p.stock
                ORDER BY deseos DESC
                LIMIT 20
            """)
            productos_top = cur.fetchall()

            # Top 10 usuarios con más favoritos
            cur.execute("""
                SELECT u.id, u.nombre, u.email, COUNT(ld.id) AS cantidad
                FROM lista_deseos ld
                JOIN usuarios u ON ld.usuario_id = u.id
                GROUP BY u.id, u.nombre, u.email
                ORDER BY cantidad DESC
                LIMIT 10
            """)
            usuarios_top = cur.fetchall()

            cur.execute("SELECT COUNT(*) AS total FROM lista_deseos")
            row = cur.fetchone()
            total_deseos = row['total'] if row else 0
    except Exception as e:
        app.logger.error(f"Error wishlist stats: {e}")

    return render_template('wishlist_estadisticas.html',
                           datosApp=datosApp,
                           productos_top=productos_top,
                           usuarios_top=usuarios_top,
                           total_deseos=total_deseos)
