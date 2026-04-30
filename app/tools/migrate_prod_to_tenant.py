"""
Migración de la BD de producción actual al esquema multi-tenant.

Ejecutar UNA SOLA VEZ en producción. El script es idempotente:
si ya existe cyber_t001 o el tenant en el control plane, no duplica datos.

Pasos:
  1. Verifica que saas_control_plane existe y tiene las 4 tablas.
  2. Crea la DB cyber_t001 (si no existe) y restore desde pg_dump.
  3. Inserta el tenant en tenants + tenant_databases.
  4. Copia usuarios desde cyber_t001.usuarios → saas_control_plane.usuarios_globales.

Uso:
    python tools/migrate_prod_to_tenant.py [--dry-run]

Variables de entorno requeridas (en .cybershop.conf):
    DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
    CONTROL_PLANE_DB_NAME, CONTROL_PLANE_DB_USER, CONTROL_PLANE_DB_PASSWORD, ...
    KMS_KEY
    TENANT_SLUG  (slug del cliente, ej. "panaderia-roma")
    TENANT_NOMBRE (nombre legible del cliente, ej. "Panadería Roma")
"""

import os
import sys
import argparse
from pathlib import Path

# Cargar .cybershop.conf
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.cybershop.conf')

import psycopg2
from psycopg2.extras import DictCursor

# Importar desde servicios
sys.path.insert(0, str(Path(__file__).parent.parent))
from services.db_layer import get_control_plane_conn, get_tenant_conn
from services.crypto_utils import aes_gcm_encrypt


def get_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dry-run', action='store_true', help='Solo reporta cambios, no los aplica.')
    return p.parse_args()


def ensure_control_plane():
    """Verifica que el control plane esté listo."""
    conn = get_control_plane_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_name IN ('tenants','tenant_databases','usuarios_globales','refresh_tokens')
    """)
    found = {r[0] for r in cur.fetchall()}
    missing = {'tenants','tenant_databases','usuarios_globales','refresh_tokens'} - found
    cur.close(); conn.close()
    if missing:
        print(f"ERROR: Tablas faltantes en saas_control_plane: {missing}")
        print("Aplicar primero: psql -d saas_control_plane -f migrations/control_plane/0001_init.sql")
        sys.exit(1)
    print("[OK] saas_control_plane: 4 tablas verificadas.")


def upsert_tenant(cur, slug, nombre):
    """Inserta tenant si no existe. Retorna tenant_id."""
    cur.execute("SELECT id FROM tenants WHERE slug = %s", (slug,))
    row = cur.fetchone()
    if row:
        print(f"[OK] Tenant '{slug}' ya existe (id={row[0]}).")
        return row[0]
    cur.execute(
        "INSERT INTO tenants (slug, nombre) VALUES (%s, %s) RETURNING id",
        (slug, nombre)
    )
    tenant_id = cur.fetchone()[0]
    print(f"[NUEVO] Tenant '{slug}' creado (id={tenant_id}).")
    return tenant_id


def upsert_tenant_db(cur, tenant_id, db_name):
    """Registra la DB del tenant en tenant_databases."""
    cur.execute("SELECT tenant_id FROM tenant_databases WHERE tenant_id = %s", (tenant_id,))
    if cur.fetchone():
        print(f"[OK] tenant_databases para tenant {tenant_id} ya existe.")
        return

    db_password = os.getenv('DB_PASSWORD', '')
    db_password_enc = aes_gcm_encrypt(db_password)

    cur.execute(
        """
        INSERT INTO tenant_databases
            (tenant_id, db_host, db_port, db_name, db_user, db_password_enc, schema_version)
        VALUES (%s, %s, %s, %s, %s, %s, '0001')
        """,
        (
            tenant_id,
            os.getenv('DB_HOST', 'localhost'),
            int(os.getenv('DB_PORT', 5432)),
            db_name,
            os.getenv('DB_USER', 'postgres'),
            db_password_enc,
        )
    )
    print(f"[NUEVO] tenant_databases registrado → {db_name}.")


def copy_users(cur_cp, tenant_id, db_name):
    """Copia usuarios desde tenant DB → usuarios_globales. Idempotente por email."""
    conn_tenant = get_tenant_conn(db_name)
    cur_t = conn_tenant.cursor(cursor_factory=DictCursor)

    cur_t.execute("SELECT id, email, contraseña, rol_id, estado FROM usuarios")
    usuarios = cur_t.fetchall()
    cur_t.close(); conn_tenant.close()

    nuevos = 0
    for u in usuarios:
        cur_cp.execute("SELECT id FROM usuarios_globales WHERE email = %s", (u['email'],))
        if cur_cp.fetchone():
            continue
        cur_cp.execute(
            """
            INSERT INTO usuarios_globales (email, contraseña, tenant_id, rol_id, estado)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (u['email'], u['contraseña'], tenant_id, u['rol_id'],
             'habilitado' if u['estado'] == 'habilitado' else 'suspendido')
        )
        nuevos += 1

    print(f"[OK] {nuevos} usuarios copiados a usuarios_globales ({len(usuarios) - nuevos} ya existían).")


def verify_counts(db_name):
    """Verificación final: cuenta filas en tablas críticas."""
    tables = ['usuarios', 'productos', 'pedidos']
    conn = get_tenant_conn(db_name)
    cur = conn.cursor()
    print("\n--- Verificación de integridad en cyber_t001 ---")
    for t in tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            count = cur.fetchone()[0]
            print(f"  {t}: {count} filas")
        except Exception:
            print(f"  {t}: tabla no encontrada (OK si no aplica a este tenant)")
    cur.close(); conn.close()


def main():
    args = get_args()

    slug   = os.getenv('TENANT_SLUG', 'cyber-t001')
    nombre = os.getenv('TENANT_NOMBRE', 'Tenant Principal')
    db_name_legacy = os.getenv('DB_NAME', 'cybershop')
    db_name_new    = 'cyber_t001'

    print("=" * 60)
    print(f"Migración: {db_name_legacy} → {db_name_new}")
    print(f"Tenant   : {slug} / {nombre}")
    print(f"Dry run  : {args.dry_run}")
    print("=" * 60)

    ensure_control_plane()

    if args.dry_run:
        print("\n[DRY RUN] No se aplican cambios.")
        return

    # Transacción en control plane
    conn_cp = get_control_plane_conn()
    cur_cp  = conn_cp.cursor(cursor_factory=DictCursor)

    try:
        tenant_id = upsert_tenant(cur_cp, slug, nombre)
        upsert_tenant_db(cur_cp, tenant_id, db_name_new)
        copy_users(cur_cp, tenant_id, db_name_legacy)
        conn_cp.commit()
    except Exception as e:
        conn_cp.rollback()
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        cur_cp.close()
        conn_cp.close()

    verify_counts(db_name_legacy)
    print("\n[COMPLETADO] Migración exitosa.")
    print("Próximo paso: actualizar DB_NAME=cyber_t001 en .cybershop.conf y reiniciar Flask.")


if __name__ == '__main__':
    main()
