#!/bin/bash
# ============================================================
# 04_deploy_app.sh
# Despliega CyberShop en /opt/cybershop, crea venv, instala deps.
# Requiere: git configurado o código copiado en /opt/cybershop
# Uso: bash 04_deploy_app.sh
# ============================================================
set -euo pipefail

BOLD='\033[1m'; GREEN='\033[0;32m'; NC='\033[0m'
ok()  { echo -e "  ${GREEN}✓${NC} $*"; }
hdr() { echo -e "\n${BOLD}▶ $*${NC}"; }

APP_DIR="/opt/cybershop"
APP_USER="cybershop"
VENV_DIR="$APP_DIR/venv"

hdr "Creando usuario del sistema: $APP_USER"
id "$APP_USER" &>/dev/null || useradd -r -m -d "$APP_DIR" -s /bin/bash "$APP_USER"
ok "Usuario $APP_USER listo"

hdr "Directorio de la app"
mkdir -p "$APP_DIR"
# Si el código aún no está, clonar o copiar aquí:
if [[ ! -f "$APP_DIR/app/app.py" ]]; then
    echo "  ATENCIÓN: Código no encontrado en $APP_DIR/app/"
    echo "  Opciones:"
    echo "  a) git clone <repo> $APP_DIR   (si tienes repositorio remoto)"
    echo "  b) rsync desde local: rsync -avz -e 'ssh -p 2222' C:/Cybershop/CyberShop/ root@38.134.148.47:/opt/cybershop/"
    echo ""
    echo "  Una vez copiado el código, volver a ejecutar este script."
    exit 1
fi
ok "Código presente en $APP_DIR"

hdr "Virtualenv Python"
if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
    ok "Venv creado en $VENV_DIR"
else
    ok "Venv ya existe"
fi

hdr "Instalando dependencias Python"
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -q
ok "Dependencias instaladas"

hdr "Claves JWT"
KEYS_DIR="$APP_DIR/app/keys"
mkdir -p "$KEYS_DIR"
chmod 700 "$KEYS_DIR"
if [[ ! -f "$KEYS_DIR/jwt_private.pem" ]]; then
    "$VENV_DIR/bin/python" "$APP_DIR/app/tools/gen_jwt_keys.py"
    chmod 600 "$KEYS_DIR/jwt_private.pem"
    ok "Claves JWT generadas"
else
    ok "Claves JWT ya existen"
fi

hdr "Directorio de configuración"
mkdir -p /etc/cybershop
chmod 750 /etc/cybershop

hdr "Permisos"
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
chmod -R 755 "$APP_DIR"
chmod 700 "$KEYS_DIR"
chmod 600 "$KEYS_DIR"/*.pem 2>/dev/null || true
ok "Permisos configurados"

hdr "Directorios de uploads y logs"
mkdir -p "$APP_DIR/app/static/media/media" \
         "$APP_DIR/app/static/user/users" \
         "$APP_DIR/app/static/uploads" \
         "$APP_DIR/app/static/cotizaciones/pdf" \
         "$APP_DIR/app/static/cuentas_cobro/pdf" \
         "$APP_DIR/logs"
chown -R "$APP_USER":"$APP_USER" "$APP_DIR/app/static" "$APP_DIR/logs"
ok "Directorios de uploads y logs creados"

echo -e "\n${BOLD}Continuar con 05_configurar_env.sh${NC}"
