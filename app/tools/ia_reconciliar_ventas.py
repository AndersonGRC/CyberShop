"""Reconciliación de SOLO LECTURA: ventas según la IA vs. el libro contable.

Hoy la IA suma las ventas desde las tablas operativas (pedidos web aprobados +
`ventas_pos` no anuladas + `pos_desktop_sales`). El reporte oficial
/admin/contabilidad/ventas suma solo `contabilidad_movimientos`. Antes de que la IA
use el libro contable como fuente, este script muestra, por mes y por canal, dónde
difieren las dos cifras en la base de un cliente.

No escribe nada: la sesión de PostgreSQL se abre en modo solo lectura.

Uso (en el servidor, con las credenciales de la instancia del cliente):
    env/bin/python tools/ia_reconciliar_ventas.py --env /etc/cybershop/cyber-t001.env [--meses 6]
    DB_NAME=cyber_t014 env/bin/python tools/ia_reconciliar_ventas.py
"""

import argparse
import os
import sys

import psycopg2
import psycopg2.extras

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENTA_CATEGORIAS = ('venta_pos', 'venta_restaurante', 'pedido_online', 'cuenta_cobro')
ANULACIONES = ('anulacion_pos', 'anulacion_restaurante')


def _conexion(env_file):
    from dotenv import dotenv_values
    valores = dict(dotenv_values(os.path.join(_APP_DIR, '.cybershop.conf')))
    if env_file:
        valores.update({k: v for k, v in dotenv_values(env_file).items() if v is not None})
    valores.update({k: os.environ[k] for k in ('DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST', 'DB_PORT')
                    if os.environ.get(k)})
    conn = psycopg2.connect(dbname=valores.get('DB_NAME'), user=valores.get('DB_USER'),
                            password=valores.get('DB_PASSWORD'), host=valores.get('DB_HOST', 'localhost'),
                            port=valores.get('DB_PORT', '5432'))
    conn.set_session(readonly=True, autocommit=True)
    return conn, valores.get('DB_NAME')


def _existe(cur, tabla):
    cur.execute("SELECT to_regclass(%s) AS t", (f'public.{tabla}',))
    return cur.fetchone()['t'] is not None


def _por_mes(cur, sql, params=()):
    cur.execute(sql, params)
    return {(r['mes'], r['canal']): (float(r['total'] or 0), int(r['n'])) for r in cur.fetchall()}


def reconciliar(cur, meses):
    desde = "date_trunc('month', CURRENT_DATE) - make_interval(months => %s)"
    ia = {}
    ia.update(_por_mes(cur, f"""
        SELECT to_char(fecha_creacion, 'YYYY-MM') mes, 'pedido_online' canal, SUM(monto_total) total, COUNT(*) n
        FROM pedidos WHERE estado_pago IN ('APROBADO','PAGADO','aprobado','pagado')
          AND fecha_creacion >= {desde} GROUP BY 1""", (meses,)))
    if _existe(cur, 'ventas_pos'):
        cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name='ventas_pos' AND column_name='origen'")
        origen = ("COALESCE(origen, CASE WHEN numero_venta LIKE 'MESA-%%' THEN 'mesa' ELSE 'pos' END)"
                  if cur.fetchone() else "CASE WHEN numero_venta LIKE 'MESA-%%' THEN 'mesa' ELSE 'pos' END")
        ia.update(_por_mes(cur, f"""
            SELECT to_char(fecha, 'YYYY-MM') mes,
                   CASE WHEN {origen} = 'mesa' THEN 'venta_restaurante' ELSE 'venta_pos' END canal,
                   SUM(total) total, COUNT(*) n
            FROM ventas_pos WHERE COALESCE(estado,'completada') <> 'anulada' AND fecha >= {desde}
            GROUP BY 1, 2""", (meses,)))
    if _existe(cur, 'pos_desktop_sales'):
        for (mes, _c), (t, n) in _por_mes(cur, f"""
                SELECT to_char(created_at_local, 'YYYY-MM') mes, 'venta_pos' canal, SUM(total) total, COUNT(*) n
                FROM pos_desktop_sales WHERE created_at_local >= {desde} GROUP BY 1""", (meses,)).items():
            t0, n0 = ia.get((mes, 'venta_pos'), (0.0, 0))
            ia[(mes, 'venta_pos')] = (t0 + t, n0 + n)

    libro, anulado = {}, {}
    if _existe(cur, 'contabilidad_movimientos'):
        libro = _por_mes(cur, f"""
            SELECT to_char(fecha, 'YYYY-MM') mes, categoria canal, SUM(monto) total, COUNT(*) n
            FROM contabilidad_movimientos WHERE tipo = 'ingreso' AND categoria = ANY(%s)
              AND fecha >= {desde} GROUP BY 1, 2""", (list(VENTA_CATEGORIAS), meses))
        anulado = _por_mes(cur, f"""
            SELECT to_char(fecha, 'YYYY-MM') mes,
                   CASE categoria WHEN 'anulacion_pos' THEN 'venta_pos' ELSE 'venta_restaurante' END canal,
                   SUM(monto) total, COUNT(*) n
            FROM contabilidad_movimientos WHERE tipo = 'egreso' AND categoria = ANY(%s)
              AND fecha >= {desde} GROUP BY 1, 2""", (list(ANULACIONES), meses))

    filas = []
    for mes, canal in sorted(set(ia) | set(libro) | set(anulado)):
        t_ia, n_ia = ia.get((mes, canal), (0.0, 0))
        t_lb, n_lb = libro.get((mes, canal), (0.0, 0))
        t_an, _ = anulado.get((mes, canal), (0.0, 0))
        filas.append({'mes': mes, 'canal': canal, 'ia': t_ia, 'ia_n': n_ia, 'libro': t_lb, 'libro_n': n_lb,
                      'anulado': t_an, 'libro_neto': t_lb - t_an,
                      'dif_bruto': t_ia - t_lb, 'dif_neto': t_ia - (t_lb - t_an)})
    return filas


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--env', help='archivo .env de la instancia del cliente (DB_NAME, DB_USER, ...)')
    ap.add_argument('--meses', type=int, default=6, help='meses hacia atrás además del actual (defecto 6)')
    args = ap.parse_args()

    conn, db = _conexion(args.env)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        filas = reconciliar(cur, max(0, min(args.meses, 36)))
    conn.close()

    etiquetas = {'venta_pos': 'POS', 'venta_restaurante': 'Mesas', 'pedido_online': 'Online',
                 'cuenta_cobro': 'Ctas cobro'}
    print(f'BD {db} — ventas según la IA vs. libro contable (solo lectura)\n')
    print(f"{'mes':<8} {'canal':<11} {'IA':>14} {'n':>5} {'libro':>14} {'n':>5} {'anulado':>12} "
          f"{'dif vs libro':>14} {'dif vs neto':>13}")
    cuadra = True
    for f in filas:
        marca = '' if abs(f['dif_neto']) < 1 or abs(f['dif_bruto']) < 1 else '  <--'
        cuadra = cuadra and not marca
        print(f"{f['mes']:<8} {etiquetas.get(f['canal'], f['canal']):<11} {f['ia']:>14,.0f} {f['ia_n']:>5} "
              f"{f['libro']:>14,.0f} {f['libro_n']:>5} {f['anulado']:>12,.0f} {f['dif_bruto']:>14,.0f} "
              f"{f['dif_neto']:>13,.0f}{marca}")
    t = {k: sum(f[k] for f in filas) for k in ('ia', 'libro', 'anulado', 'libro_neto')}
    print(f"\nTOTAL    IA {t['ia']:,.0f} · libro {t['libro']:,.0f} · anulado {t['anulado']:,.0f} · "
          f"libro neto {t['libro_neto']:,.0f}")
    print('Cuadra en todos los meses y canales.' if cuadra else
          'Hay diferencias (marcadas con <--): revisarlas antes de cambiar la fuente de la IA.')
    return 0 if cuadra else 2


if __name__ == '__main__':
    sys.exit(main())
