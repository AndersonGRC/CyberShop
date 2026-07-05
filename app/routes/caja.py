"""
routes/caja.py — Caja del POS: apertura con base, movimientos de efectivo y cuadre/arqueo.

Modelo (patrón de los locales en Colombia):
  1. APERTURA: el cajero abre la caja con una "base" (efectivo YA existente —
     NO se registra como ingreso en contabilidad para no duplicar dinero).
  2. Durante el día: las ventas POS se estampan con `caja_sesion_id`; las salidas
     de efectivo (gastos menores, retiros a banco) SÍ crean un egreso contable
     al momento; las entradas (agregar sencillo) son traslados, sin movimiento.
  3. CIERRE/CUADRE: el cajero cuenta el efectivo; el sistema calcula
        esperado = base + ventas EFECTIVO + entradas − salidas
     y la diferencia (contado − esperado). Sobrante → ingreso `sobrante_caja`;
     faltante → egreso `faltante_caja` (solo si diferencia ≠ 0).

Reglas:
  - UNA sola caja abierta a la vez (índice único parcial + FOR UPDATE);
    varios turnos secuenciales por día están bien.
  - El POS bloquea el cobro sin caja abierta (409 en procesar_venta_pos).
  - Tablas creadas perezosamente por tenant (patrón _ensure_metodos_pago).
  - "Efectivo" = metodo_pago 'EFECTIVO' (código sembrado por defecto).
"""

import json
import math

from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, jsonify, current_app)

from database import get_db_cursor, get_db_connection
from helpers import get_data_app
from security import permiso_requerido, registrar_guard_permiso, rol_requerido, POS_OPERATIONAL, ADMIN_CONTADOR
from tenant_features import MODULE_CAJA, module_required

caja_bp = Blueprint('caja', __name__)

# Permisos dinámicos (matriz del Propietario): guard 'ver' de todo el
# blueprint. Convive con los @rol_requerido existentes (defensa doble).
registrar_guard_permiso(caja_bp, 'caja')

CODIGO_EFECTIVO = 'EFECTIVO'

CATEGORIAS_MOVIMIENTO = [
    ('gasto_caja',    'Gasto menor (domicilio, insumo…)'),
    ('retiro_banco',  'Retiro / consignación a banco'),
    ('ingreso_extra', 'Ingreso de efectivo extra'),
    ('otro',          'Otro'),
]


# ─────────────────────────────────────────────────────────
# TABLAS (creación perezosa por tenant)
# ─────────────────────────────────────────────────────────

def _ensure_caja_tables(cur):
    """Crea las tablas de caja si no existen (idempotente, solo aditivo)."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS caja_sesiones (
            id                SERIAL PRIMARY KEY,
            estado            VARCHAR(10)   NOT NULL DEFAULT 'abierta',
            base_inicial      NUMERIC(14,2) NOT NULL DEFAULT 0,
            usuario_apertura  INTEGER,
            fecha_apertura    TIMESTAMP     NOT NULL DEFAULT NOW(),
            notas_apertura    TEXT,
            efectivo_esperado NUMERIC(14,2),
            efectivo_contado  NUMERIC(14,2),
            diferencia        NUMERIC(14,2),
            total_ventas      NUMERIC(14,2),
            resumen_metodos   JSONB,
            notas_cierre      TEXT,
            usuario_cierre    INTEGER,
            fecha_cierre      TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS caja_sesiones_una_abierta
            ON caja_sesiones (estado) WHERE estado = 'abierta'
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS caja_movimientos (
            id             SERIAL PRIMARY KEY,
            caja_sesion_id INTEGER NOT NULL REFERENCES caja_sesiones(id),
            tipo           VARCHAR(10)   NOT NULL CHECK (tipo IN ('entrada','salida')),
            categoria      VARCHAR(40)   NOT NULL DEFAULT 'gasto_caja',
            descripcion    TEXT,
            monto          NUMERIC(14,2) NOT NULL CHECK (monto > 0),
            usuario_id     INTEGER,
            fecha          TIMESTAMP     NOT NULL DEFAULT NOW()
        )
    """)
    cur.execute("ALTER TABLE ventas_pos ADD COLUMN IF NOT EXISTS caja_sesion_id INTEGER")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ventas_pos_caja ON ventas_pos (caja_sesion_id)")


# ─────────────────────────────────────────────────────────
# HELPERS PÚBLICOS — usados por routes/admin.py (POS)
# ─────────────────────────────────────────────────────────

def get_caja_abierta():
    """Sesión de caja abierta (dict) o None. NO crea tablas: los tenants que
    nunca han usado caja simplemente reciben None (la tabla no existe aún)."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT id, base_inicial, fecha_apertura, usuario_apertura
                FROM caja_sesiones WHERE estado = 'abierta' LIMIT 1
            """)
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception:
        return None


def _resumen_sesion(cur, sesion):
    """Resumen vivo de una sesión: ventas por método, entradas/salidas y
    efectivo esperado. `cur` debe ser dict_cursor; `sesion` dict de la fila."""
    cur.execute("""
        SELECT metodo_pago, COUNT(*) AS n, COALESCE(SUM(total), 0) AS total
        FROM ventas_pos
        WHERE caja_sesion_id = %s AND COALESCE(estado, 'activa') <> 'anulada'
        GROUP BY metodo_pago ORDER BY total DESC
    """, (sesion['id'],))
    metodos = [dict(r) for r in cur.fetchall()]
    total_ventas = sum(float(m['total']) for m in metodos)
    total_efectivo = sum(float(m['total']) for m in metodos
                         if (m['metodo_pago'] or '').upper() == CODIGO_EFECTIVO)

    cur.execute("""
        SELECT tipo, COALESCE(SUM(monto), 0) AS total
        FROM caja_movimientos WHERE caja_sesion_id = %s GROUP BY tipo
    """, (sesion['id'],))
    movs = {r['tipo']: float(r['total']) for r in cur.fetchall()}
    entradas = movs.get('entrada', 0.0)
    salidas = movs.get('salida', 0.0)

    base = float(sesion.get('base_inicial') or 0)
    esperado = base + total_efectivo + entradas - salidas
    return {
        'metodos': metodos,
        'total_ventas': total_ventas,
        'total_efectivo': total_efectivo,
        'entradas': entradas,
        'salidas': salidas,
        'base': base,
        'esperado': esperado,
    }


def _registrar_egreso_contable(categoria, descripcion, monto, referencia_tipo, referencia_id):
    """Egreso en contabilidad (no lanza — registrar_movimiento ya es silencioso)."""
    try:
        from routes.contabilidad import registrar_movimiento
        registrar_movimiento(
            tipo='egreso', categoria=categoria, descripcion=descripcion,
            monto=monto, referencia_tipo=referencia_tipo, referencia_id=referencia_id,
            usuario_id=session.get('usuario_id'), auto_generado=True)
    except Exception as e:
        try:
            current_app.logger.warning(f"caja→contabilidad egreso falló: {e}")
        except Exception:
            pass


def _monto(valor):
    """Parsea un monto del form: acepta '50.000', '50000', '50000.50'.

    Rechaza (ValueError) valores no numéricos, no finitos (inf/nan) o fuera del
    rango de NUMERIC(14,2). Sin esta guarda, 'nan'/'inf' pasaban las validaciones
    (`< 0` / `<= 0` dan False con nan/inf) y envenenaban el arqueo/contabilidad."""
    s = str(valor or '').strip().replace('$', '').replace(' ', '')
    if not s:
        return 0.0
    # '50.000' estilo CO (miles con punto) → quitar puntos si no hay decimales reales
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    elif s.count('.') > 1 or (s.count('.') == 1 and len(s.split('.')[1]) == 3):
        s = s.replace('.', '')
    n = float(s)   # ValueError si no es número
    if not math.isfinite(n) or abs(n) >= 1e12:  # descarta inf/nan y overflow de NUMERIC(14,2)
        raise ValueError('monto fuera de rango')
    return n


# ─────────────────────────────────────────────────────────
# RUTAS
# ─────────────────────────────────────────────────────────

@caja_bp.route('/admin/pos/caja')
@rol_requerido(POS_OPERATIONAL)
@module_required(MODULE_CAJA)
def caja_estado():
    """Página principal de caja: apertura o resumen vivo + cierre."""
    datosApp = get_data_app()
    with get_db_cursor(dict_cursor=True) as cur:
        _ensure_caja_tables(cur)
        cur.execute("SELECT * FROM caja_sesiones WHERE estado = 'abierta' LIMIT 1")
        sesion = cur.fetchone()
        resumen, movimientos = None, []
        if sesion:
            sesion = dict(sesion)
            resumen = _resumen_sesion(cur, sesion)
            cur.execute("""
                SELECT m.*, u.nombre AS usuario_nombre
                FROM caja_movimientos m LEFT JOIN usuarios u ON u.id = m.usuario_id
                WHERE m.caja_sesion_id = %s ORDER BY m.fecha DESC
            """, (sesion['id'],))
            movimientos = [dict(r) for r in cur.fetchall()]
        # Últimas sesiones cerradas (vistazo rápido)
        cur.execute("""
            SELECT id, fecha_apertura, fecha_cierre, base_inicial, total_ventas,
                   efectivo_esperado, efectivo_contado, diferencia
            FROM caja_sesiones WHERE estado = 'cerrada'
            ORDER BY fecha_cierre DESC LIMIT 5
        """)
        recientes = [dict(r) for r in cur.fetchall()]
    es_admin_contador = session.get('rol_id') in ADMIN_CONTADOR
    return render_template('caja.html', datosApp=datosApp, sesion=sesion,
                           resumen=resumen, movimientos=movimientos, recientes=recientes,
                           categorias_mov=CATEGORIAS_MOVIMIENTO,
                           es_admin_contador=es_admin_contador)


@caja_bp.route('/admin/pos/caja/abrir', methods=['POST'])
@rol_requerido(POS_OPERATIONAL)
@module_required(MODULE_CAJA)
def abrir_caja():
    """Abre la caja con la base. Acepta form (página de caja) y JSON (modal del POS).
    La base es dinero ya existente: NO genera movimiento contable."""
    es_json = request.is_json
    data = request.get_json(silent=True) if es_json else request.form
    try:
        base = _monto((data or {}).get('base'))
    except (TypeError, ValueError):
        base = -1
    notas = ((data or {}).get('notas') or '').strip() or None
    if base < 0:
        msg = 'La base debe ser un valor válido (0 o más).'
        if es_json:
            return jsonify({'success': False, 'error': msg}), 400
        flash(msg, 'error')
        return redirect(url_for('caja.caja_estado'))

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        _ensure_caja_tables(cur)
        # Anti doble-apertura (doble clic / dos cajeros a la vez)
        cur.execute("SELECT id FROM caja_sesiones WHERE estado = 'abierta' FOR UPDATE")
        if cur.fetchone():
            conn.rollback()
            msg = 'Ya hay una caja abierta.'
            if es_json:
                return jsonify({'success': False, 'error': msg}), 409
            flash(msg, 'warning')
            return redirect(url_for('caja.caja_estado'))
        cur.execute("""
            INSERT INTO caja_sesiones (base_inicial, usuario_apertura, notas_apertura)
            VALUES (%s, %s, %s) RETURNING id, base_inicial
        """, (base, session.get('usuario_id'), notas))
        sesion_id, base_db = cur.fetchone()
        conn.commit()
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"abrir_caja: {e}")
        msg = 'No se pudo abrir la caja. Intenta de nuevo.'
        if es_json:
            return jsonify({'success': False, 'error': msg}), 500
        flash(msg, 'error')
        return redirect(url_for('caja.caja_estado'))
    finally:
        conn.close()

    if es_json:
        return jsonify({'success': True, 'sesion_id': sesion_id, 'base': float(base_db)})
    flash(f'Caja abierta con base ${base:,.0f}.'.replace(',', '.'), 'success')
    return redirect(url_for('caja.caja_estado'))


@caja_bp.route('/admin/pos/caja/movimiento', methods=['POST'])
@rol_requerido(POS_OPERATIONAL)
@module_required(MODULE_CAJA)
def movimiento_caja():
    """Entrada/salida de efectivo del turno. Las salidas crean egreso contable."""
    tipo = (request.form.get('tipo') or '').strip()
    categoria = (request.form.get('categoria') or 'gasto_caja').strip()
    descripcion = (request.form.get('descripcion') or '').strip()
    try:
        monto = _monto(request.form.get('monto'))
    except (TypeError, ValueError):
        monto = 0
    if tipo not in ('entrada', 'salida') or monto <= 0:
        flash('Movimiento inválido: revisa el tipo y el monto.', 'error')
        return redirect(url_for('caja.caja_estado'))
    if categoria not in dict(CATEGORIAS_MOVIMIENTO):
        categoria = 'otro'

    mov_id = None
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT id FROM caja_sesiones WHERE estado = 'abierta' LIMIT 1")
        sesion = cur.fetchone()
        if not sesion:
            flash('No hay caja abierta.', 'warning')
            return redirect(url_for('caja.caja_estado'))
        cur.execute("""
            INSERT INTO caja_movimientos (caja_sesion_id, tipo, categoria, descripcion, monto, usuario_id)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        """, (sesion['id'], tipo, categoria, descripcion or None, monto,
              session.get('usuario_id')))
        mov_id = cur.fetchone()['id']

    if tipo == 'salida' and mov_id:
        # El dinero SALE del negocio (o va al banco) → egreso contable al momento
        _registrar_egreso_contable(
            categoria=categoria if categoria in ('gasto_caja', 'retiro_banco') else 'gasto_caja',
            descripcion=f"Salida de caja: {descripcion or 'sin descripción'}",
            monto=monto, referencia_tipo='caja_movimiento', referencia_id=mov_id)

    flash(f"{'Entrada' if tipo == 'entrada' else 'Salida'} de ${monto:,.0f} registrada.".replace(',', '.'), 'success')
    return redirect(url_for('caja.caja_estado'))


@caja_bp.route('/admin/pos/caja/cerrar', methods=['POST'])
@rol_requerido(POS_OPERATIONAL)
@module_required(MODULE_CAJA)
def cerrar_caja():
    """Cuadre: el cajero cuenta el efectivo, el sistema calcula la diferencia,
    congela el snapshot por método y publica sobrante/faltante en contabilidad."""
    try:
        contado = _monto(request.form.get('efectivo_contado'))
    except (TypeError, ValueError):
        contado = -1
    notas = (request.form.get('notas') or '').strip() or None
    if contado < 0:
        flash('Indica el efectivo contado (0 o más).', 'error')
        return redirect(url_for('caja.caja_estado'))

    conn = get_db_connection()
    try:
        from psycopg2.extras import DictCursor
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute("SELECT * FROM caja_sesiones WHERE estado = 'abierta' FOR UPDATE")
        sesion = cur.fetchone()
        if not sesion:
            conn.rollback()
            flash('No hay caja abierta para cerrar.', 'warning')
            return redirect(url_for('caja.caja_estado'))
        sesion = dict(sesion)
        resumen = _resumen_sesion(cur, sesion)
        diferencia = round(contado - resumen['esperado'], 2)
        snapshot = {
            'metodos': [{'codigo': m['metodo_pago'], 'n': int(m['n']),
                         'total': float(m['total'])} for m in resumen['metodos']],
            'entradas': resumen['entradas'], 'salidas': resumen['salidas'],
        }
        cur.execute("""
            UPDATE caja_sesiones
            SET estado = 'cerrada', efectivo_esperado = %s, efectivo_contado = %s,
                diferencia = %s, total_ventas = %s, resumen_metodos = %s,
                notas_cierre = %s, usuario_cierre = %s, fecha_cierre = NOW()
            WHERE id = %s
        """, (resumen['esperado'], contado, diferencia, resumen['total_ventas'],
              json.dumps(snapshot), notas, session.get('usuario_id'), sesion['id']))
        conn.commit()
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"cerrar_caja: {e}")
        flash('No se pudo cerrar la caja. Intenta de nuevo.', 'error')
        return redirect(url_for('caja.caja_estado'))
    finally:
        conn.close()

    # Sobrante/faltante → contabilidad (fuera de la transacción del cierre,
    # igual que las ventas POS: si falla, solo se pierde el movimiento contable)
    if diferencia > 0:
        try:
            from routes.contabilidad import registrar_movimiento
            registrar_movimiento(
                tipo='ingreso', categoria='sobrante_caja',
                descripcion=f"Sobrante cuadre de caja #{sesion['id']}",
                monto=diferencia, referencia_tipo='caja_cierre',
                referencia_id=sesion['id'],
                usuario_id=session.get('usuario_id'), auto_generado=True)
        except Exception as e:
            current_app.logger.warning(f"caja sobrante→contabilidad: {e}")
    elif diferencia < 0:
        _registrar_egreso_contable(
            categoria='faltante_caja',
            descripcion=f"Faltante cuadre de caja #{sesion['id']}",
            monto=abs(diferencia), referencia_tipo='caja_cierre',
            referencia_id=sesion['id'])

    flash('Caja cerrada. Este es el arqueo del turno.', 'success')
    return redirect(url_for('caja.arqueo_sesion', sesion_id=sesion['id']))


@caja_bp.route('/admin/pos/caja/sesion/<int:sesion_id>')
@rol_requerido(POS_OPERATIONAL)
@module_required(MODULE_CAJA)
def arqueo_sesion(sesion_id):
    """Detalle/arqueo de una sesión, con tiquete imprimible de 80mm."""
    datosApp = get_data_app()
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT s.*, ua.nombre AS nombre_apertura, uc.nombre AS nombre_cierre
            FROM caja_sesiones s
            LEFT JOIN usuarios ua ON ua.id = s.usuario_apertura
            LEFT JOIN usuarios uc ON uc.id = s.usuario_cierre
            WHERE s.id = %s
        """, (sesion_id,))
        sesion = cur.fetchone()
        if not sesion:
            flash('Sesión de caja no encontrada.', 'error')
            return redirect(url_for('caja.caja_estado'))
        sesion = dict(sesion)
        if sesion['estado'] == 'cerrada' and sesion.get('resumen_metodos'):
            snap = sesion['resumen_metodos']
            if isinstance(snap, str):
                snap = json.loads(snap)
            resumen = {
                'metodos': [{'metodo_pago': m['codigo'], 'n': m['n'], 'total': m['total']}
                            for m in snap.get('metodos', [])],
                'entradas': snap.get('entradas', 0), 'salidas': snap.get('salidas', 0),
                'base': float(sesion.get('base_inicial') or 0),
                'total_ventas': float(sesion.get('total_ventas') or 0),
                'esperado': float(sesion.get('efectivo_esperado') or 0),
            }
        else:
            resumen = _resumen_sesion(cur, sesion)
        cur.execute("""
            SELECT m.*, u.nombre AS usuario_nombre
            FROM caja_movimientos m LEFT JOIN usuarios u ON u.id = m.usuario_id
            WHERE m.caja_sesion_id = %s ORDER BY m.fecha
        """, (sesion_id,))
        movimientos = [dict(r) for r in cur.fetchall()]
    return render_template('caja_arqueo.html', datosApp=datosApp, sesion=sesion,
                           resumen=resumen, movimientos=movimientos)


@caja_bp.route('/admin/pos/caja/historial')
@rol_requerido(ADMIN_CONTADOR)
@permiso_requerido('accounting', 'ver')   # cuadres = dato contable; no cede con solo 'caja ver'
@module_required(MODULE_CAJA)
def historial_caja():
    """Reporte de cuadres: una fila por sesión con base/ventas/esperado/contado/diferencia."""
    from datetime import date, timedelta
    datosApp = get_data_app()
    desde = request.args.get('desde') or (date.today() - timedelta(days=30)).isoformat()
    hasta = request.args.get('hasta') or date.today().isoformat()
    sesiones = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT s.*, ua.nombre AS nombre_apertura, uc.nombre AS nombre_cierre
                FROM caja_sesiones s
                LEFT JOIN usuarios ua ON ua.id = s.usuario_apertura
                LEFT JOIN usuarios uc ON uc.id = s.usuario_cierre
                WHERE s.fecha_apertura::date BETWEEN %s AND %s
                ORDER BY s.fecha_apertura DESC
            """, (desde, hasta))
            sesiones = [dict(r) for r in cur.fetchall()]
    except Exception:
        pass  # tenant sin tablas de caja aún
    return render_template('caja_historial.html', datosApp=datosApp,
                           sesiones=sesiones, desde=desde, hasta=hasta)
