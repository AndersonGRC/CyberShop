"""
routes/blog_admin.py — Administración del blog SEO del tenant.

CRUD de artículos + asistente IA "✦ Generar artículo" (borrador completo que
el dueño revisa y publica). El blog público se activa con la sección
'mostrar_blog' (default OFF) desde el sitio público admin.

Protección: rol staff (matriz dinámica módulo 'content') + módulo content.
"""
from datetime import datetime

from flask import (Blueprint, flash, jsonify, redirect, render_template,
                   request, session, url_for)

from database import get_db_cursor
from helpers import get_data_app
from security import ADMIN_STAFF, permiso_requerido, rol_requerido

blog_admin_bp = Blueprint('blog_admin', __name__, url_prefix='/admin/blog')


def _slugify(texto):
    import re as _re
    t = (texto or '').lower().translate(str.maketrans('áéíóúüñ', 'aeiouun'))
    return _re.sub(r'[^a-z0-9]+', '-', t).strip('-')[:170]


def _slug_unico(cur, slug, excluir_id=None):
    base, n = slug or 'articulo', 1
    candidato = base
    while True:
        if excluir_id:
            cur.execute("SELECT 1 FROM blog_posts WHERE slug=%s AND id<>%s",
                        (candidato, excluir_id))
        else:
            cur.execute("SELECT 1 FROM blog_posts WHERE slug=%s", (candidato,))
        if not cur.fetchone():
            return candidato
        n += 1
        candidato = f"{base}-{n}"


@blog_admin_bp.route('/')
@rol_requerido(ADMIN_STAFF)
@permiso_requerido('content', 'ver')
def lista():
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT id, slug, titulo, estado, keyword_objetivo,
                              fecha_publicado, updated_at
                       FROM blog_posts ORDER BY updated_at DESC""")
        posts = cur.fetchall()
    return render_template('blog_admin.html', datosApp=get_data_app(),
                           posts=posts, post=None)


@blog_admin_bp.route('/nuevo', methods=['GET', 'POST'])
@blog_admin_bp.route('/<int:post_id>/editar', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
@permiso_requerido('content', 'operar')
def editar(post_id=None):
    post = None
    if post_id:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT * FROM blog_posts WHERE id=%s", (post_id,))
            post = cur.fetchone()
        if not post:
            flash('Artículo no encontrado.', 'error')
            return redirect(url_for('blog_admin.lista'))

    if request.method == 'POST':
        f = {k: (request.form.get(k) or '').strip()
             for k in ('titulo', 'slug', 'meta_descripcion', 'extracto',
                       'cuerpo_html', 'keyword_objetivo', 'imagen', 'accion')}
        if len(f['titulo']) < 5 or len(f['cuerpo_html']) < 50:
            flash('El artículo necesita título y contenido.', 'error')
        else:
            publicar = f['accion'] == 'publicar'
            with get_db_cursor(dict_cursor=True) as cur:
                slug = _slug_unico(cur, _slugify(f['slug'] or f['titulo']),
                                   excluir_id=post_id)
                if post_id:
                    cur.execute("""
                        UPDATE blog_posts SET titulo=%s, slug=%s,
                            meta_descripcion=%s, extracto=%s, cuerpo_html=%s,
                            keyword_objetivo=%s, imagen=%s, updated_at=NOW(),
                            estado = CASE WHEN %s THEN 'publicado' ELSE estado END,
                            fecha_publicado = CASE WHEN %s AND fecha_publicado IS NULL
                                                   THEN NOW() ELSE fecha_publicado END
                        WHERE id=%s
                    """, (f['titulo'], slug, f['meta_descripcion'], f['extracto'],
                          f['cuerpo_html'], f['keyword_objetivo'], f['imagen'],
                          publicar, publicar, post_id))
                else:
                    cur.execute("""
                        INSERT INTO blog_posts (titulo, slug, meta_descripcion,
                            extracto, cuerpo_html, keyword_objetivo, imagen,
                            autor, estado, fecha_publicado)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                    """, (f['titulo'], slug, f['meta_descripcion'], f['extracto'],
                          f['cuerpo_html'], f['keyword_objetivo'], f['imagen'],
                          session.get('username') or 'Equipo',
                          'publicado' if publicar else 'borrador',
                          datetime.now() if publicar else None))
                    post_id = cur.fetchone()['id']
            flash('Artículo publicado.' if publicar else 'Borrador guardado.', 'success')
            return redirect(url_for('blog_admin.editar', post_id=post_id))

    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT id, slug, titulo, estado, keyword_objetivo,
                              fecha_publicado, updated_at
                       FROM blog_posts ORDER BY updated_at DESC""")
        posts = cur.fetchall()
    return render_template('blog_admin.html', datosApp=get_data_app(),
                           posts=posts, post=post)


@blog_admin_bp.route('/<int:post_id>/estado', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@permiso_requerido('content', 'operar')
def cambiar_estado(post_id):
    accion = (request.form.get('accion') or '').strip()
    with get_db_cursor() as cur:
        if accion == 'publicar':
            cur.execute("""UPDATE blog_posts SET estado='publicado',
                           fecha_publicado=COALESCE(fecha_publicado, NOW()),
                           updated_at=NOW() WHERE id=%s""", (post_id,))
            flash('Artículo publicado.', 'success')
        elif accion == 'despublicar':
            cur.execute("UPDATE blog_posts SET estado='borrador', updated_at=NOW() WHERE id=%s",
                        (post_id,))
            flash('Artículo pasado a borrador.', 'success')
    return redirect(url_for('blog_admin.lista'))


@blog_admin_bp.route('/<int:post_id>/eliminar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@permiso_requerido('content', 'eliminar')
def eliminar(post_id):
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM blog_posts WHERE id=%s", (post_id,))
    flash('Artículo eliminado.', 'success')
    return redirect(url_for('blog_admin.lista'))


@blog_admin_bp.route('/generar-ia', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@permiso_requerido('content', 'operar')
def generar_ia():
    """✦ La IA redacta el borrador completo (el dueño revisa y publica)."""
    from tenant_features import is_module_active, MODULE_AI
    if not is_module_active(MODULE_AI):
        return jsonify({'success': False,
                        'error': 'El Asistente IA no está incluido en tu plan.'}), 403
    d = request.get_json(silent=True) or {}
    from services.ai_service import generar_articulo_blog
    articulo, err = generar_articulo_blog(d.get('tema'), d.get('keyword'),
                                          d.get('publico'))
    if err:
        return jsonify({'success': False, 'error': err}), 200
    return jsonify({'success': True, 'articulo': articulo})
