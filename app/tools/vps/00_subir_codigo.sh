#!/bin/bash
# ============================================================
# 00_subir_codigo.sh — Sincroniza el código local → VPS
# Ejecutar desde Windows en Git Bash / terminal con ssh.
#
# Uso:
#   bash tools/vps/00_subir_codigo.sh
#
# Lo que hace:
#   rsync el directorio CyberShop/  → root@VPS:/opt/cybershop/
#   Excluye: venv/, __pycache__, *.pyc, .git, .cybershop.conf,
#            keys/*.pem (las claves se generan en el VPS)
# ============================================================

VPS_HOST="38.134.148.47"
VPS_PORT="2222"
VPS_USER="root"
LOCAL_SRC="$(cd "$(dirname "$0")/../../../.." && pwd)/"   # raíz de CyberShop/
REMOTE_DST="/opt/cybershop/"

echo "Subiendo código:"
echo "  Local : $LOCAL_SRC"
echo "  Remoto: $VPS_USER@$VPS_HOST:$REMOTE_DST (puerto $VPS_PORT)"
echo ""

rsync -avz --progress \
    -e "ssh -p $VPS_PORT" \
    --exclude 'venv/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '*.pyo' \
    --exclude '.git/' \
    --exclude 'app/.cybershop.conf' \
    --exclude 'app/keys/*.pem' \
    --exclude 'app/static/cotizaciones/pdf/*' \
    --exclude 'app/static/cuentas_cobro/pdf/*' \
    --exclude 'app/static/media/media/*' \
    --exclude 'app/static/user/users/*' \
    --exclude '*.log' \
    --exclude '*.sqlite3' \
    --exclude '*.db' \
    "$LOCAL_SRC" \
    "$VPS_USER@$VPS_HOST:$REMOTE_DST"

echo ""
echo "Código sincronizado."
echo "Próximo paso en el VPS: bash /opt/cybershop/app/tools/vps/01_diagnostico.sh"
