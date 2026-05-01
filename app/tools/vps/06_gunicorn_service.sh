#!/bin/bash
# ============================================================
# 06_gunicorn_service.sh
# Crea y arranca el servicio systemd de CyberShop (Gunicorn)
# Uso: bash 06_gunicorn_service.sh
# ============================================================
set -euo pipefail

BOLD='\033[1m'; GREEN='\033[0;32m'; NC='\033[0m'
ok()  { echo -e "  ${GREEN}✓${NC} $*"; }
hdr() { echo -e "\n${BOLD}▶ $*${NC}"; }

APP_DIR="/opt/cybershop"
SERVICE="/etc/systemd/system/cybershop.service"

hdr "Instalando Gunicorn"
"$APP_DIR/venv/bin/pip" install gunicorn -q
ok "Gunicorn instalado"

hdr "Creando servicio systemd"
cat > "$SERVICE" <<'EOF'
[Unit]
Description=CyberShop Flask App (Gunicorn)
After=network.target postgresql.service redis-server.service
Wants=postgresql.service redis-server.service

[Service]
Type=notify
User=cybershop
Group=cybershop
WorkingDirectory=/opt/cybershop/app
Environment="PATH=/opt/cybershop/venv/bin"
ExecStart=/opt/cybershop/venv/bin/gunicorn \
    --workers 4 \
    --worker-class sync \
    --bind 127.0.0.1:8000 \
    --timeout 120 \
    --access-logfile /opt/cybershop/logs/access.log \
    --error-logfile /opt/cybershop/logs/error.log \
    --log-level info \
    app:app
ExecReload=/bin/kill -s HUP $MAINPID
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

ok "Archivo de servicio creado"

hdr "Activando y arrancando servicio"
systemctl daemon-reload
systemctl enable cybershop
systemctl start cybershop
sleep 2
systemctl is-active cybershop && ok "Servicio cybershop activo" || {
    echo "  Revisar logs: journalctl -u cybershop -n 30"
    journalctl -u cybershop -n 20 --no-pager
    exit 1
}

hdr "Smoke test local"
curl -sf http://127.0.0.1:8000/api/v1/health 2>/dev/null && ok "Health endpoint responde" \
    || echo "  API aún no disponible (normal si CYBERSHOP_API_ENABLED=0 o DB no configurada)"

echo -e "\n${BOLD}Continuar con 07_caddy.sh${NC}"
