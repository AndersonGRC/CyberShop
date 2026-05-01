#!/bin/bash
# ============================================================
# 05_configurar_env.sh
# Genera /opt/cybershop/app/.cybershop.conf con todos los
# valores reales del VPS. Editar las variables al inicio.
# Uso: bash 05_configurar_env.sh
# ============================================================
set -euo pipefail

# ── COMPLETAR ANTES DE EJECUTAR (copiar desde .cybershop.conf local) ──
# Nunca subir este archivo al repo con valores reales.
FLASK_SECRET_KEY=""                # copiar de .cybershop.conf → FLASK_SECRET_KEY
DB_PASSWORD=""                     # ⚠ el password que genera 03_setup_postgres.sh
KMS_KEY=""                         # copiar de .cybershop.conf → KMS_KEY
PAYU_API_KEY=""
PAYU_API_LOGIN=""
PAYU_MERCHANT_ID=""
PAYU_ACCOUNT_ID=""
PAYU_ENV="production"
MAIL_USERNAME=""
MAIL_PASSWORD=""
GOOGLE_CLIENT_ID=""
GOOGLE_CLIENT_SECRET=""
RECAPTCHA_SECRET_KEY=""
TENANT_SLUG="cyber-t001"
TENANT_NOMBRE="CyberShop Demo"
BILLING_NOMBRE=""
BILLING_ID=""
BILLING_TELEFONO=""
BILLING_EMAIL=""
DIAN_SERVICE_URL="http://127.0.0.1:5003/api/v1"
DIAN_API_KEY=""
DIAN_MASTER_KEY=""
DIAN_UI_URL="https://portaltributario.cybershopcol.com/ui"
# ───────────────────────────────────────────────────────────

BOLD='\033[1m'; RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
ok()  { echo -e "  ${GREEN}✓${NC} $*"; }
err() { echo -e "  ${RED}✗ ERROR:${NC} $*"; exit 1; }
hdr() { echo -e "\n${BOLD}▶ $*${NC}"; }

APP_DIR="/opt/cybershop/app"
CONF="$APP_DIR/.cybershop.conf"

hdr "Validando variables requeridas"
[[ -z "$FLASK_SECRET_KEY" ]] && err "FLASK_SECRET_KEY vacío. Generar y completar arriba."
[[ -z "$DB_PASSWORD" ]]      && err "DB_PASSWORD vacío. Usar el generado por 03_setup_postgres.sh."
[[ -z "$KMS_KEY" ]]          && err "KMS_KEY vacío. Generar y completar arriba."

KEY_DIR="$APP_DIR/keys"
[[ ! -f "$KEY_DIR/jwt_private.pem" ]] && err "jwt_private.pem no encontrada en $KEY_DIR. Ejecutar 04_deploy_app.sh primero."
ok "Variables validadas"

hdr "Escribiendo $CONF"
cat > "$CONF" <<EOF
# CyberShop — Configuración VPS (generado por 05_configurar_env.sh)
# NUNCA versionar este archivo.

# Flask
FLASK_SECRET_KEY=$FLASK_SECRET_KEY
FLASK_DEBUG=false

# Base de Datos tenant activo
DB_NAME=cyber_t001
DB_USER=cybershop_app
DB_PASSWORD=$DB_PASSWORD
DB_HOST=localhost
DB_PORT=5432

# Control Plane
CONTROL_PLANE_DB_NAME=saas_control_plane

# Tenant por defecto
DEFAULT_TENANT_ID=1
DEFAULT_TENANT_SLUG=$TENANT_SLUG

# JWT RS256
JWT_PRIVATE_KEY_PATH=$KEY_DIR/jwt_private.pem
JWT_PUBLIC_KEY_PATH=$KEY_DIR/jwt_public.pem
JWT_ACCESS_TTL_SECONDS=900
JWT_REFRESH_TTL_SECONDS=2592000

# API
CYBERSHOP_API_ENABLED=1
APP_VERSION=1.0.0

# KMS
KMS_KEY=$KMS_KEY

# Redis
REDIS_URL=redis://localhost:6379/0

# Migración
TENANT_SLUG=$TENANT_SLUG
TENANT_NOMBRE=$TENANT_NOMBRE

# PayU
PAYU_API_KEY=$PAYU_API_KEY
PAYU_API_LOGIN=$PAYU_API_LOGIN
PAYU_MERCHANT_ID=$PAYU_MERCHANT_ID
PAYU_ACCOUNT_ID=$PAYU_ACCOUNT_ID
PAYU_ENV=$PAYU_ENV
PAYU_RESPONSE_URL=https://app.cybershopcol.com/respuesta-pago
PAYU_CONFIRMATION_URL=https://app.cybershopcol.com/confirmacion-pago

# Mail
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=$MAIL_USERNAME
MAIL_PASSWORD=$MAIL_PASSWORD
MAIL_DEFAULT_SENDER=$MAIL_USERNAME

# Google OAuth
GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET=$GOOGLE_CLIENT_SECRET
GOOGLE_REDIRECT_URI=https://app.cybershopcol.com/admin/google/callback
GOOGLE_GMAIL_REDIRECT_URI=https://app.cybershopcol.com/admin/google/gmail/callback
GOOGLE_LOGIN_REDIRECT_URI=https://app.cybershopcol.com/google/login/callback

# reCAPTCHA
RECAPTCHA_SECRET_KEY=$RECAPTCHA_SECRET_KEY

# Seguridad
SESSION_COOKIE_SECURE=true

# Billing (cuentas de cobro)
BILLING_NOMBRE=$BILLING_NOMBRE
BILLING_ID=$BILLING_ID
BILLING_TELEFONO=$BILLING_TELEFONO
BILLING_EMAIL=$BILLING_EMAIL

# DIAN facturación electrónica
DIAN_SERVICE_URL=$DIAN_SERVICE_URL
DIAN_API_KEY=$DIAN_API_KEY
DIAN_MASTER_KEY=$DIAN_MASTER_KEY
DIAN_UI_URL=$DIAN_UI_URL
EOF

chmod 600 "$CONF"
chown cybershop:cybershop "$CONF"
ok "Archivo de configuración creado ($CONF)"

echo -e "\n${BOLD}Continuar con 06_gunicorn_service.sh${NC}"
