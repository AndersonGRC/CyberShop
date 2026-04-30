#!/bin/bash
# ============================================================
# 07_caddy.sh
# Configura Caddy 2 para app.cybershopcol.com con TLS auto.
# REQUISITO: DNS A record "app.cybershopcol.com" → 38.134.148.47
#            ya propagado (verificar con: dig app.cybershopcol.com +short)
# Uso: bash 07_caddy.sh
# ============================================================
set -euo pipefail

BOLD='\033[1m'; RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✓${NC} $*"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $*"; }
err()  { echo -e "  ${RED}✗ ERROR:${NC} $*"; exit 1; }
hdr()  { echo -e "\n${BOLD}▶ $*${NC}"; }

DOMAIN="app.cybershopcol.com"
VPS_IP="38.134.148.47"

hdr "Verificando propagación DNS"
RESOLVED=$(dig +short "$DOMAIN" 2>/dev/null | tail -1)
if [[ "$RESOLVED" == "$VPS_IP" ]]; then
    ok "DNS propagado: $DOMAIN → $RESOLVED"
else
    warn "DNS aún no propagado o apunta a otra IP: '$RESOLVED' (esperado: $VPS_IP)"
    warn "Caddy intentará el challenge de Let's Encrypt de todos modos."
    warn "Si falla TLS, ejecutar este script de nuevo cuando DNS propague."
fi

hdr "Verificando que puertos 80 y 443 no estén ocupados"
if ss -tlnp | grep -qE ':(80|443)\b'; then
    echo "  Procesos usando 80/443:"
    ss -tlnp | grep -E ':(80|443)\b'
    warn "Detener Nginx u otro servidor web antes de continuar."
    systemctl stop nginx 2>/dev/null || true
    systemctl disable nginx 2>/dev/null || true
    ok "Nginx detenido"
fi

hdr "Escribiendo Caddyfile"
cat > /etc/caddy/Caddyfile <<EOF
# CyberShop — Caddyfile
# Generado por 07_caddy.sh

$DOMAIN {
    # Proxy hacia Gunicorn
    reverse_proxy 127.0.0.1:8000 {
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }

    # Logs estructurados
    log {
        output file /opt/cybershop/logs/caddy_access.log {
            roll_size 10mb
            roll_keep 5
        }
        format json
    }

    # Headers de seguridad
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
        X-Content-Type-Options nosniff
        X-Frame-Options SAMEORIGIN
        Referrer-Policy strict-origin-when-cross-origin
        -Server
    }

    # Archivos estáticos servidos directamente por Caddy (más rápido)
    handle /static/* {
        root * /opt/cybershop/app
        file_server
    }
}

# Redirigir HTTP → HTTPS automáticamente (Caddy lo hace por defecto)
EOF

ok "Caddyfile escrito"

hdr "Validando sintaxis del Caddyfile"
caddy validate --config /etc/caddy/Caddyfile && ok "Caddyfile válido" || err "Caddyfile con errores"

hdr "Reiniciando Caddy"
systemctl enable caddy
systemctl restart caddy
sleep 3
systemctl is-active caddy && ok "Caddy activo" || {
    echo "  Revisar: journalctl -u caddy -n 30"
    journalctl -u caddy -n 20 --no-pager
    exit 1
}

hdr "Smoke test HTTPS"
sleep 5  # Dar tiempo a Let's Encrypt para emitir cert
curl -sf "https://$DOMAIN/api/v1/health" 2>/dev/null \
    && ok "HTTPS OK: https://$DOMAIN/api/v1/health responde" \
    || warn "HTTPS aún no disponible — puede tardar 30–60 s para cert Let's Encrypt"

echo ""
echo -e "${BOLD}URL de la aplicación: https://$DOMAIN${NC}"
echo -e "${BOLD}Continuar con 08_firewall.sh${NC}"
