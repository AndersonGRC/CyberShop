#!/bin/bash
# ============================================================
# 09_searxng.sh
# SearXNG propio para las referencias de internet del chat del sitio
# (dudas de compatibilidad/uso de un producto, módulo ai_public_compat).
#
# - Contenedor Docker publicado SOLO en 127.0.0.1:8888: nadie de afuera lo usa.
# - Sin llaves ni cupos de terceros. Limiter apagado porque solo lo usa la app.
# - Límites de memoria/CPU para no competir con las instancias de CyberShop.
# - Idempotente: si ya existe, lo recrea con la misma clave secreta.
#
# La app lo busca en SEARXNG_URL (por defecto http://127.0.0.1:8888): si no
# está corriendo, el chat responde igual, sin referencias.
#
# Uso (root):  bash 09_searxng.sh
# Quitarlo:    docker rm -f searxng   (la app sigue funcionando sin referencias)
# ============================================================
set -euo pipefail

BOLD='\033[1m'; RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✓${NC} $*"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $*"; }
err()  { echo -e "  ${RED}✗ ERROR:${NC} $*"; exit 1; }
hdr()  { echo -e "\n${BOLD}▶ $*${NC}"; }

NOMBRE="searxng"
IMAGEN="docker.io/searxng/searxng:latest"
PUERTO="127.0.0.1:8888"
DIR_CONF="/etc/searxng"

hdr "Requisitos"
[[ $EUID -eq 0 ]] || err "ejecutar como root"
command -v docker >/dev/null 2>&1 || err "Docker no está instalado. No se instala solo: decide antes si se agrega al servidor."
docker info >/dev/null 2>&1 || err "Docker está instalado pero el servicio no responde (systemctl status docker)"
ok "Docker $(docker --version | awk '{print $3}' | tr -d ,)"
if ss -ltn | awk '{print $4}' | grep -q "^${PUERTO}$" && ! docker ps --format '{{.Names}}' | grep -qx "$NOMBRE"; then
    err "el puerto ${PUERTO} ya lo usa otro proceso"
fi

hdr "Configuración en ${DIR_CONF}"
mkdir -p "$DIR_CONF"
if [[ -f "$DIR_CONF/settings.yml" ]] && grep -q 'secret_key:' "$DIR_CONF/settings.yml"; then
    SECRETO=$(awk -F'"' '/secret_key:/ {print $2; exit}' "$DIR_CONF/settings.yml")
    ok "se conserva la clave secreta existente"
else
    SECRETO=$(openssl rand -hex 32)
    ok "clave secreta nueva"
fi
cat > "$DIR_CONF/settings.yml" <<EOF
# Generado por tools/vps/09_searxng.sh — solo lo consulta CyberShop desde 127.0.0.1
use_default_settings: true
general:
  instance_name: "cybershop-referencias"
  enable_metrics: false
server:
  secret_key: "${SECRETO}"
  limiter: false
  public_instance: false
  image_proxy: false
  method: "GET"
search:
  safe_search: 1
  default_lang: "es"
  formats:
    - html
    - json
outgoing:
  request_timeout: 3.0
  max_request_timeout: 4.0
EOF
chmod 640 "$DIR_CONF/settings.yml"
ok "settings.yml escrito (json activo, limiter apagado)"

hdr "Contenedor"
docker pull -q "$IMAGEN" >/dev/null
docker rm -f "$NOMBRE" >/dev/null 2>&1 || true
docker run -d --name "$NOMBRE" --restart unless-stopped \
    -p "${PUERTO}:8080" \
    -v "$DIR_CONF:/etc/searxng" \
    --memory 512m --cpus 1 \
    --log-opt max-size=10m --log-opt max-file=3 \
    "$IMAGEN" >/dev/null
ok "contenedor ${NOMBRE} arriba en ${PUERTO}"

hdr "Prueba"
for i in $(seq 1 30); do
    curl -fs "http://${PUERTO}/healthz" >/dev/null 2>&1 && break
    sleep 1
done
N=$(curl -fs "http://${PUERTO}/search?q=cargador+portatil+asus+vivobook+especificaciones&format=json&language=es" \
    | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("results", [])))' 2>/dev/null || echo 0)
if [[ "$N" -gt 0 ]]; then
    ok "búsqueda de prueba: ${N} resultados"
else
    warn "la búsqueda de prueba no trajo resultados (¿salida a internet bloqueada o buscadores lentos?). Revisar: docker logs ${NOMBRE}"
fi
curl -fs -o /dev/null -m 3 "http://$(hostname -I | awk '{print $1}'):8888/" 2>/dev/null \
    && warn "¡responde por la IP pública! revisar el -p" || ok "no responde desde afuera de 127.0.0.1"
