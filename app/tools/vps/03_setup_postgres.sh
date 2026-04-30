#!/bin/bash
# ============================================================
# 03_setup_postgres.sh
# Crea: saas_control_plane DB + usuario cybershop_app
# Requiere: PostgreSQL 16 corriendo
# Uso: bash 03_setup_postgres.sh
# ============================================================
set -euo pipefail

BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✓${NC} $*"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $*"; }
hdr()  { echo -e "\n${BOLD}▶ $*${NC}"; }

# ── Configuración ──────────────────────────────────────────────────
APP_DB_USER="cybershop_app"
APP_DB_PASS="${CYBERSHOP_DB_PASS:-$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 32)}"
CONTROL_DB="saas_control_plane"
TENANT_DB="cyber_t001"    # Se crea vacía; migrate_prod_to_tenant.py la llenará
# ───────────────────────────────────────────────────────────────────

hdr "Creando usuario de base de datos: $APP_DB_USER"
su -c "psql -c \"
DO \\\$\\\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$APP_DB_USER') THEN
    CREATE ROLE $APP_DB_USER LOGIN PASSWORD '$APP_DB_PASS';
  END IF;
END\\\$\\\$;
\"" postgres
ok "Usuario $APP_DB_USER listo"

hdr "Creando DB: $CONTROL_DB"
su -c "psql -c \"
SELECT 'existe' FROM pg_database WHERE datname='$CONTROL_DB'
\" | grep -q existe || createdb -O $APP_DB_USER $CONTROL_DB" postgres
ok "$CONTROL_DB lista"

hdr "Creando extensiones en $CONTROL_DB"
su -c "psql -d $CONTROL_DB -c 'CREATE EXTENSION IF NOT EXISTS citext; CREATE EXTENSION IF NOT EXISTS pgcrypto;'" postgres
ok "citext + pgcrypto instaladas"

hdr "Aplicando schema del control plane"
# El SQL se sube con scp o se copia a mano — verificar que existe
SQL_PATH="/opt/cybershop/app/migrations/control_plane/0001_init.sql"
if [[ -f "$SQL_PATH" ]]; then
    su -c "psql -d $CONTROL_DB -f '$SQL_PATH'" postgres
    ok "Schema control plane aplicado"
else
    warn "No se encontró $SQL_PATH — aplicar manualmente después del deploy:"
    warn "  psql -d $CONTROL_DB -f /opt/cybershop/app/migrations/control_plane/0001_init.sql"
fi

hdr "Creando DB tenant: $TENANT_DB (vacía, se llena con migrate_prod_to_tenant.py)"
su -c "psql -c \"
SELECT 'existe' FROM pg_database WHERE datname='$TENANT_DB'
\" | grep -q existe || createdb -O $APP_DB_USER $TENANT_DB" postgres
ok "$TENANT_DB lista"

hdr "Permisos"
su -c "psql -c \"GRANT ALL PRIVILEGES ON DATABASE $CONTROL_DB TO $APP_DB_USER;\"" postgres
su -c "psql -c \"GRANT ALL PRIVILEGES ON DATABASE $TENANT_DB TO $APP_DB_USER;\"" postgres
su -c "psql -d $CONTROL_DB -c \"GRANT ALL ON SCHEMA public TO $APP_DB_USER;\"" postgres
su -c "psql -d $TENANT_DB  -c \"GRANT ALL ON SCHEMA public TO $APP_DB_USER;\"" postgres
ok "Permisos configurados"

hdr "Configurar pg_hba para conexiones locales con contraseña"
PG_HBA=$(find /etc/postgresql -name pg_hba.conf 2>/dev/null | head -1)
if [[ -n "$PG_HBA" ]]; then
    # Asegurar que la línea local usa md5 o scram-sha-256, no peer para cybershop_app
    if ! grep -q "cybershop_app" "$PG_HBA"; then
        sed -i '/^local.*all.*all/i local   all             cybershop_app                           scram-sha-256' "$PG_HBA"
        systemctl reload postgresql
        ok "pg_hba.conf actualizado"
    else
        ok "pg_hba.conf ya tiene entrada para cybershop_app"
    fi
fi

echo ""
echo "════════════════════════════════════════════════════"
echo "  Credenciales a guardar en .cybershop.conf del VPS:"
echo ""
echo "  DB_USER=$APP_DB_USER"
echo "  DB_PASSWORD=$APP_DB_PASS"
echo "  DB_NAME=$TENANT_DB"
echo "  DB_HOST=localhost"
echo "  CONTROL_PLANE_DB_NAME=$CONTROL_DB"
echo "════════════════════════════════════════════════════"
echo ""
echo -e "${BOLD}Continuar con 04_deploy_app.sh${NC}"
