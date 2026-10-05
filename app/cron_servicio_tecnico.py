"""
cron_servicio_tecnico.py — Seguimiento diario del módulo Servicio Técnico.

Ejecutar una vez al día por instancia de cliente (7:30 Colombia), solo donde el
módulo esté encendido (si está apagado, no hace nada):
  30 7 * * *  cd /var/www/CyberShop/app && env/bin/python cron_servicio_tecnico.py

Qué hace:
  1. Revisa las cotizaciones pendientes y programa su recordatorio.
  2. Envía por correo los recordatorios vencidos de clientes con correo
     (encuesta, garantía, mantenimiento, equipo listo sin recoger, revisión
     de pieza), si está encendido en Configuración. Los demás quedan en
     la bandeja «Hoy» para WhatsApp.
  3. Envía al dueño el resumen del día, si lo activó en Configuración.

Opciones:
  --prueba   no envía nada: muestra el resumen y cuántos recordatorios saldrían
  --forzar   envía el resumen aunque esté apagado o ya haya salido hoy
"""

import os
import sys

_app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _app_dir)
os.chdir(_app_dir)

from app import app  # noqa: E402


def main():
    prueba = '--prueba' in sys.argv
    forzar = '--forzar' in sys.argv
    with app.app_context():
        import tenant_features as tf
        from services import servicio_tecnico_seguimiento as seg
        from services import servicio_tecnico_service as st

        if not tf.is_module_active(tf.MODULE_SERVICIO_TECNICO, tenant_id=tf.get_default_tenant_id() or 1):
            print('[INFO] Servicio Técnico apagado en esta tienda: nada que hacer.')
            return 0
        if not st.asegurar_tablas():
            print('[ERROR] No están las tablas del módulo.')
            return 1

        seg.sincronizar_cotizaciones()
        if prueba:
            res = seg.enviar_resumen(prueba=True)
            pendientes = seg.contar_pendientes()
            print(f'[PRUEBA] seguimientos para hoy o atrasados: {pendientes}')
            print(f"[PRUEBA] asunto: {res['asunto']}")
            print(f"[PRUEBA] destinos: {', '.join(res['destinos']) or '(sin destinatarios)'}")
            print(res['texto'])
            return 0

        enviados = seg.enviar_vencidos_por_correo()
        print(f'[OK] recordatorios enviados por correo: {enviados}')
        res = seg.enviar_resumen(forzar=forzar)
        if res.get('enviado'):
            print(f"[OK] resumen enviado a {', '.join(res['destinos'])}")
            if res.get('fallidos'):
                print(f"[AVISO] no se pudo enviar a {', '.join(res['fallidos'])}")
        else:
            print(f"[INFO] resumen no enviado: {res.get('motivo')}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
