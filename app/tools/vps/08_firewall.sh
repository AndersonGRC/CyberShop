#!/bin/bash
# ============================================================
# 08_firewall.sh
# Configura UFW: permite SSH (2222), HTTP (80), HTTPS (443).
# Bloquea Postgres y Redis a conexiones externas.
# Uso: bash 08_firewall.sh
# ============================================================
set -euo pipefail

BOLD='\033[1m'; GREEN='\033[0;32m'; NC='\033[0m'
ok()  { echo -e "  ${GREEN}✓${NC} $*"; }
hdr() { echo -e "\n${BOLD}▶ $*${NC}"; }

hdr "Configurando UFW"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing

# SSH en puerto 2222
ufw allow 2222/tcp comment 'SSH'

# Web
ufw allow 80/tcp  comment 'HTTP (Let'\''s Encrypt challenge)'
ufw allow 443/tcp comment 'HTTPS'

# Rechazar acceso externo a Postgres y Redis (solo localhost)
ufw deny 5432/tcp comment 'PostgreSQL - solo localhost'
ufw deny 6379/tcp comment 'Redis - solo localhost'

# Gunicorn solo interno (ya lo bloquea el bind 127.0.0.1:8000)
ufw deny 8000/tcp comment 'Gunicorn - solo interno'

ufw --force enable
ok "UFW habilitado"

hdr "Reglas activas"
ufw status verbose

hdr "Configurando fail2ban para SSH"
cat > /etc/fail2ban/jail.d/cybershop.conf <<'EOF'
[sshd]
enabled  = true
port     = 2222
maxretry = 5
bantime  = 3600
findtime = 600
EOF
systemctl restart fail2ban
ok "fail2ban configurado (SSH port 2222, 5 intentos → ban 1h)"

echo -e "\n${BOLD}Firewall listo. Setup VPS completo.${NC}"
echo ""
echo "Próximos pasos manuales:"
echo "  1. Copiar el código si aún no está en /opt/cybershop/"
echo "  2. Ejecutar 03_setup_postgres.sh (si no se hizo)"
echo "  3. Ejecutar 05_configurar_env.sh con las credenciales reales"
echo "  4. Reiniciar servicio: systemctl restart cybershop"
echo "  5. Verificar: curl https://app.cybershopcol.com/api/v1/health"
