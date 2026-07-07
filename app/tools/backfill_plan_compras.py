# -*- coding: utf-8 -*-
"""Backfill de cartera: incorpora al motor de cobro recurrente (plan_compras)
los tenants creados A MANO desde fADMIN, que hoy no reciben recordatorios ni
tienen link de pago.

Para cada tenant `activo` del control plane (excepto el tenant 1, el operador)
sin fila ACTIVADA en plan_compras:
  - plan_key: mapeo inverso de tenants.plan (estandar/basico → software-cybershop,
    ultra → ultra)
  - proximo_pago: tenant_billing.proxima_fecha (fallback hoy+30)
  - email/nombre del dueño: usuario rol 2 del tenant (fallback rol 1, fallback
    cliente_config empresa_email)
  - dominio: tenant_runtime (custom_domain > subdominio.cybershopcol.com)
  - token_renovacion nuevo → el link /renovar/<token> queda operativo YA.

Uso:
    python tools/backfill_plan_compras.py --dry-run   # solo muestra
    python tools/backfill_plan_compras.py             # inserta
"""
import secrets
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app  # noqa: E402

PLAN_INVERSO = {'ultra': 'ultra', 'estandar': 'software-cybershop',
                'basico': 'software-cybershop', 'standard': 'software-cybershop'}


def _dueno_del_tenant(db_name):
    """(nombre, email, telefono) del dueño: usuario rol 2, fallback rol 1,
    fallback email de empresa en cliente_config."""
    from services.db_layer import tenant_cursor
    try:
        with tenant_cursor(db_name=db_name, dict_cursor=True) as cur:
            cur.execute("SELECT nombre, email, telefono FROM usuarios "
                        "WHERE rol_id IN (2, 1) AND estado = 'habilitado' "
                        "ORDER BY rol_id DESC, id LIMIT 1")
            row = cur.fetchone()
            if row and row['email']:
                return row['nombre'], row['email'], row.get('telefono') or ''
            cur.execute("SELECT valor FROM cliente_config WHERE clave = 'empresa_email'")
            row = cur.fetchone()
            if row and row['valor']:
                return None, row['valor'], ''
    except Exception as exc:  # noqa: BLE001
        print(f"    [!] no pude leer dueño de {db_name}: {exc}")
    return None, None, ''


def main(dry_run):
    from services.db_layer import control_plane_cursor
    from services import plan_compras_service as pcs
    from database import get_db_cursor

    pcs._ensure_table()

    with control_plane_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT t.id, t.slug, t.nombre, t.plan,
                   td.db_name,
                   tb.proxima_fecha, tb.monto_mensual,
                   tr.subdomain, tr.custom_domain
            FROM tenants t
            JOIN tenant_databases td ON td.tenant_id = t.id
            LEFT JOIN tenant_billing tb ON tb.tenant_id = t.id
            LEFT JOIN tenant_runtime tr ON tr.tenant_id = t.id
            WHERE t.estado = 'activo' AND t.id <> 1
            ORDER BY t.id
        """)
        tenants = cur.fetchall()

    print(f"{len(tenants)} tenant(s) activos en el control plane (sin contar el operador)")
    nuevos = 0
    for t in tenants:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT id FROM plan_compras WHERE tenant_id = %s "
                        "AND estado = 'ACTIVADA'", (t['id'],))
            if cur.fetchone():
                print(f"  [ok] tenant {t['id']} ({t['slug']}): ya está en el motor")
                continue

        plan_key = PLAN_INVERSO.get((t['plan'] or '').strip().lower(), 'software-cybershop')
        proximo = t['proxima_fecha'] or (date.today() + timedelta(days=30))
        dominio = (t['custom_domain'] or
                   (f"{t['subdomain']}.cybershopcol.com" if t['subdomain']
                    else f"{t['slug']}.cybershopcol.com"))
        nombre, email, tel = _dueno_del_tenant(t['db_name'])
        if not email:
            print(f"  [SKIP] tenant {t['id']} ({t['slug']}): sin email de dueño — "
                  "configúralo y reintenta")
            continue

        print(f"  [{'DRY' if dry_run else 'ADD'}] tenant {t['id']} ({t['slug']}): "
              f"plan={plan_key} vence={proximo} dueño={email} dominio={dominio}")
        if dry_run:
            nuevos += 1
            continue

        token_renov = secrets.token_urlsafe(24)
        with get_db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO plan_compras
                    (referencia_pedido, plan_key, buyer_nombre, buyer_email,
                     buyer_telefono, nombre_negocio, estado, tenant_id, slug,
                     dominio, periodo, proximo_pago, token_renovacion,
                     activated_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'ACTIVADA', %s, %s, %s, 'mes',
                        %s, %s, NOW())
                ON CONFLICT (referencia_pedido) DO NOTHING
                """,
                (f"BACKFILL-T{t['id']}", plan_key, nombre or t['nombre'], email,
                 tel, t['nombre'], t['id'], t['slug'], dominio, proximo,
                 token_renov),
            )
        print(f"        link de pago: https://cybershopcol.com/renovar/{token_renov}")
        nuevos += 1

    print(f"\n{'Se incorporarían' if dry_run else 'Incorporados'} {nuevos} tenant(s) al motor.")


if __name__ == '__main__':
    dry = '--dry-run' in sys.argv
    with app.app_context():
        main(dry)
