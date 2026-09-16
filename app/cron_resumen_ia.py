"""
cron_resumen_ia.py — Resumen diario del negocio por correo.

Ejecutar una vez al día por instancia de cliente (7:00 Colombia):
  0 7 * * *  cd /var/www/CyberShop/app && env/bin/python cron_resumen_ia.py

Solo envía si el cliente lo activó desde el panel del Asistente IA
(cliente_config.ia_resumen_correo_activo) y si no se envió ya hoy.

Opciones:
  --prueba   arma el correo y lo imprime, sin enviarlo
  --forzar   envía aunque esté desactivado o ya se haya enviado hoy
"""

import os
import sys

_app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _app_dir)
os.chdir(_app_dir)

from app import app  # noqa: E402
from services.ia_resumen_correo import enviar_diario  # noqa: E402


def main():
    prueba = '--prueba' in sys.argv
    forzar = '--forzar' in sys.argv
    with app.app_context():
        res = enviar_diario(forzar=forzar, prueba=prueba)
    if prueba:
        print(f"[PRUEBA] asunto: {res.get('asunto')}")
        print(f"[PRUEBA] destinos: {', '.join(res.get('destinos') or []) or '(sin destinatarios)'}")
        print(res.get('texto', ''))
        return 0
    if res.get('enviado'):
        print(f"[OK] resumen enviado a {', '.join(res['destinos'])}")
        if res.get('fallidos'):
            print(f"[AVISO] no se pudo enviar a {', '.join(res['fallidos'])}")
        return 0
    print(f"[INFO] no se envió: {res.get('motivo') or res}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
