#!/bin/bash
# ============================================================
# 00_subir_codigo.sh — Despliega el código en el VPS via git
# Ejecutar desde Windows (Git Bash) o cualquier terminal con ssh.
#
# Uso:
#   bash tools/vps/00_subir_codigo.sh
#
# Lo que hace:
#   1. Verifica conectividad SSH al VPS
#   2. Si /opt/cybershop no existe → git clone
#      Si ya existe              → git pull (origin master)
#   3. Crea /opt/cybershop/app/keys/ y /opt/cybershop/app/sql_logs/
#
# Requisito: el repo debe estar en GitHub (push antes de ejecutar)
# ============================================================

VPS_HOST="38.134.148.47"
VPS_PORT="2222"
VPS_USER="root"
REPO_URL="https://github.com/AndersonGRC/CyberShop.git"
REMOTE_DST="/opt/cybershop"

BOLD='\033[1m'; GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'
ok()  { echo -e "  ${GREEN}✓${NC} $*"; }
err() { echo -e "  ${RED}✗${NC} $*"; exit 1; }

echo -e "${BOLD}── Verificando conectividad SSH ──${NC}"
ssh -p "$VPS_PORT" -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new \
    "$VPS_USER@$VPS_HOST" "echo OK" 2>/dev/null || err "No se puede conectar a $VPS_HOST:$VPS_PORT"
ok "SSH OK"

echo ""
echo -e "${BOLD}── Desplegando código en VPS ──${NC}"
ssh -p "$VPS_PORT" "$VPS_USER@$VPS_HOST" bash <<REMOTE
set -e

if [ ! -d "$REMOTE_DST/.git" ]; then
    echo "Clonando repositorio..."
    git clone "$REPO_URL" "$REMOTE_DST"
else
    echo "Actualizando repositorio..."
    cd "$REMOTE_DST"
    git fetch origin
    git reset --hard origin/master
fi

# Crear directorios que no van al repo
mkdir -p "$REMOTE_DST/app/keys"
mkdir -p "$REMOTE_DST/app/sql_logs"
mkdir -p "$REMOTE_DST/app/static/cotizaciones/pdf"
mkdir -p "$REMOTE_DST/app/static/cuentas_cobro/pdf"
mkdir -p "$REMOTE_DST/app/static/media/media"
mkdir -p "$REMOTE_DST/app/static/user/users"

echo "Listo. Commit en VPS:"
cd "$REMOTE_DST" && git log --oneline -3
REMOTE

echo ""
ok "Código desplegado en $VPS_HOST:$REMOTE_DST"
echo -e "\nPróximo paso en el VPS:"
echo "  ssh -p $VPS_PORT $VPS_USER@$VPS_HOST"
echo "  bash $REMOTE_DST/app/tools/vps/01_diagnostico.sh"
