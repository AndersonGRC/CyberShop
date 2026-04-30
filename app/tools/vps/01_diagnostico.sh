#!/bin/bash
# ============================================================
# 01_diagnostico.sh — Estado actual del VPS
# Ejecutar PRIMERO, antes de instalar nada.
# Uso: bash 01_diagnostico.sh
# ============================================================
set -euo pipefail

BOLD='\033[1m'; RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC} $*"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $*"; }
err()  { echo -e "  ${RED}✗${NC} $*"; }
hdr()  { echo -e "\n${BOLD}── $* ──${NC}"; }

hdr "Sistema"
uname -a
echo "Uptime: $(uptime -p 2>/dev/null || uptime)"

hdr "Recursos"
free -h | head -2
df -h / | tail -1
echo "CPUs: $(nproc)"

hdr "Python"
python3 --version 2>&1 && ok "python3 presente" || err "python3 FALTA"
pip3 --version 2>&1 && ok "pip3 presente" || warn "pip3 falta"
python3 -c "import venv" 2>/dev/null && ok "venv disponible" || warn "python3-venv falta"

hdr "PostgreSQL"
if psql --version 2>/dev/null; then
    ok "psql instalado"
    PG_VER=$(psql --version | grep -oP '\d+\.\d+' | head -1)
    [[ "${PG_VER%%.*}" -ge 16 ]] && ok "versión $PG_VER >= 16" || warn "versión $PG_VER — se recomienda 16"
    systemctl is-active postgresql 2>/dev/null && ok "servicio activo" || warn "servicio no activo o nombre diferente"
    su -c "psql -c '\l'" postgres 2>/dev/null | head -20 || warn "no se puede listar DBs aún"
else
    err "PostgreSQL NO instalado"
fi

hdr "Redis"
if redis-cli --version 2>/dev/null; then
    ok "redis-cli instalado"
    redis-cli ping 2>/dev/null && ok "Redis responde" || warn "Redis no responde"
else
    err "Redis NO instalado"
fi

hdr "Caddy"
caddy version 2>/dev/null && ok "Caddy instalado" || err "Caddy NO instalado"

hdr "Nginx (verificar conflictos con Caddy)"
nginx -v 2>/dev/null && warn "Nginx instalado — verificar si usa puertos 80/443" || ok "Nginx no instalado"

hdr "Puertos en uso"
ss -tlnp | grep -E ':(80|443|5001|5432|6379|2222|8000)\b' || echo "  (ninguno de los esperados en uso)"

hdr "Servicios activos relevantes"
systemctl list-units --type=service --state=active 2>/dev/null \
  | grep -iE "cybershop|gunicorn|flask|nginx|caddy|postgresql|redis|supervisor" \
  || echo "  ninguno encontrado"

hdr "Archivos de la app"
ls /var/www/ 2>/dev/null || echo "  /var/www/ no existe"
ls /home/cybershop/ 2>/dev/null || echo "  /home/cybershop/ no existe"

echo -e "\n${BOLD}Diagnóstico completo.${NC}"
