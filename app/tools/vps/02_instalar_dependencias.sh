#!/bin/bash
# ============================================================
# 02_instalar_dependencias.sh
# Instala: PostgreSQL 16, Redis, Caddy, Python 3.11+, pip, venv
# Sistema destino: Ubuntu 22.04 / 24.04
# Uso: bash 02_instalar_dependencias.sh
# ============================================================
set -euo pipefail

BOLD='\033[1m'; GREEN='\033[0;32m'; NC='\033[0m'
ok()  { echo -e "  ${GREEN}✓${NC} $*"; }
hdr() { echo -e "\n${BOLD}▶ $*${NC}"; }

hdr "Actualizando paquetes del sistema"
apt-get update -qq
apt-get upgrade -y -qq

hdr "Instalando dependencias base"
apt-get install -y -qq \
    curl wget gnupg2 ca-certificates lsb-release \
    build-essential python3 python3-pip python3-venv python3-dev \
    libpq-dev git unzip ufw fail2ban

hdr "PostgreSQL 16"
if ! command -v psql &>/dev/null || [[ "$(psql --version | grep -oP '\d+' | head -1)" -lt 16 ]]; then
    # Repositorio oficial PGDG
    install -d /usr/share/postgresql-common/pgdg
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
         -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
    sh -c 'echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
        https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list'
    apt-get update -qq
    apt-get install -y -qq postgresql-16 postgresql-client-16
    ok "PostgreSQL 16 instalado"
else
    ok "PostgreSQL $(psql --version) ya instalado"
fi

systemctl enable postgresql
systemctl start postgresql
ok "Servicio PostgreSQL activo"

hdr "Redis 7"
if ! command -v redis-cli &>/dev/null; then
    apt-get install -y -qq redis-server
    ok "Redis instalado"
else
    ok "Redis ya instalado"
fi
systemctl enable redis-server
systemctl start redis-server
redis-cli ping | grep -q PONG && ok "Redis responde" || echo "  ⚠ Redis no responde aún"

hdr "Caddy 2"
if ! command -v caddy &>/dev/null; then
    apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
        | tee /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq
    apt-get install -y -qq caddy
    ok "Caddy instalado"
else
    ok "Caddy $(caddy version) ya instalado"
fi

hdr "Verificación final"
echo "  Python  : $(python3 --version)"
echo "  pip     : $(pip3 --version)"
echo "  psql    : $(psql --version)"
echo "  Redis   : $(redis-cli --version)"
echo "  Caddy   : $(caddy version)"
echo "  Git     : $(git --version)"

echo -e "\n${BOLD}Dependencias instaladas. Continuar con 03_setup_postgres.sh${NC}"
