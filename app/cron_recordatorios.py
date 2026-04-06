"""
cron_recordatorios.py — Envio diario de recordatorios de tareas pendientes.

Ejecutar via cron cada mañana (ej. 8:00 AM):
  0 8 * * * cd /var/www/CyberShop/app && /var/www/CyberShop/app/env/bin/python cron_recordatorios.py

Busca tareas con recordatorio_diario=TRUE, estado='pendiente' y asignado_a
con email, y envia un correo de recordatorio a cada usuario asignado.
"""

import sys
import os

# Asegurar que el directorio de la app este en el path y sea el CWD
_app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _app_dir)
os.chdir(_app_dir)

from app import app
from database import get_db_cursor
from helpers_gmail import enviar_email_gmail
from datetime import date


def enviar_recordatorios():
    with app.app_context():
        try:
            with get_db_cursor(dict_cursor=True) as cur:
                cur.execute("""
                    SELECT t.id, t.titulo, t.descripcion, t.prioridad,
                           t.fecha_limite,
                           c.nombre AS contacto_nombre,
                           u.nombre AS asignado_nombre,
                           u.email  AS asignado_email
                    FROM crm_tareas t
                    JOIN crm_contactos c ON t.contacto_id = c.id
                    JOIN usuarios u ON t.asignado_a = u.id
                    WHERE t.recordatorio_diario = TRUE
                      AND t.estado = 'pendiente'
                      AND u.email IS NOT NULL
                      AND u.email != ''
                """)
                tareas = cur.fetchall()
        except Exception as e:
            print(f"[ERROR] No se pudieron obtener las tareas: {e}")
            return

        if not tareas:
            print("[INFO] No hay tareas pendientes con recordatorio diario.")
            return

        hoy = date.today()
        enviados = 0
        errores = 0

        for t in tareas:
            # Calcular dias
            if t['fecha_limite']:
                delta = (t['fecha_limite'] - hoy).days
                if delta > 0:
                    fecha_info = f"Faltan {delta} día{'s' if delta != 1 else ''}"
                    fecha_color = '#28a745'
                elif delta == 0:
                    fecha_info = "Vence HOY"
                    fecha_color = '#ffc107'
                else:
                    fecha_info = f"Vencida hace {abs(delta)} día{'s' if abs(delta) != 1 else ''}"
                    fecha_color = '#dc3545'
                fecha_txt = str(t['fecha_limite'])
            else:
                fecha_info = 'Sin fecha límite'
                fecha_color = '#6c757d'
                fecha_txt = 'Sin fecha'

            color_prioridad = {'alta': '#dc3545', 'media': '#ffc107', 'baja': '#28a745'}.get(t['prioridad'], '#6c757d')
            texto_prioridad = t['prioridad'].capitalize()
            desc_txt = t['descripcion'] or 'Sin descripción'

            cuerpo_plano = (
                f"Recordatorio: tienes una tarea pendiente\n\n"
                f"  Título:       {t['titulo']}\n"
                f"  Contacto:     {t['contacto_nombre']}\n"
                f"  Prioridad:    {texto_prioridad}\n"
                f"  Fecha límite: {fecha_txt} ({fecha_info})\n"
                f"  Descripción:  {desc_txt}\n"
            )

            cuerpo_html = f"""
            <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:600px;margin:0 auto;border:1px solid #e0e0e0;border-radius:12px;overflow:hidden;">
                <div style="background:linear-gradient(135deg,#e67e22,#d35400);padding:24px 30px;">
                    <h2 style="color:#fff;margin:0;font-size:20px;">
                        &#128276; Recordatorio de tarea pendiente
                    </h2>
                </div>
                <div style="padding:28px 30px;background:#fff;">
                    <p style="margin:0 0 18px;color:#555;">
                        Hola <strong>{t['asignado_nombre']}</strong>, tienes una tarea pendiente:
                    </p>
                    <table style="width:100%;border-collapse:collapse;margin-bottom:16px;">
                        <tr>
                            <td style="padding:10px 14px;background:#f4f6fb;font-weight:600;color:#555;width:130px;">Título</td>
                            <td style="padding:10px 14px;background:#f4f6fb;color:#222;font-weight:600;">{t['titulo']}</td>
                        </tr>
                        <tr>
                            <td style="padding:10px 14px;font-weight:600;color:#555;">Contacto</td>
                            <td style="padding:10px 14px;color:#222;">{t['contacto_nombre']}</td>
                        </tr>
                        <tr>
                            <td style="padding:10px 14px;background:#f4f6fb;font-weight:600;color:#555;">Prioridad</td>
                            <td style="padding:10px 14px;background:#f4f6fb;">
                                <span style="display:inline-block;background:{color_prioridad};color:#fff;padding:3px 12px;border-radius:12px;font-size:0.85em;font-weight:600;">{texto_prioridad}</span>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding:10px 14px;font-weight:600;color:#555;">Fecha límite</td>
                            <td style="padding:10px 14px;color:#222;">
                                {fecha_txt}
                                <span style="display:inline-block;background:{fecha_color};color:#fff;padding:2px 10px;border-radius:10px;font-size:0.8em;margin-left:8px;">{fecha_info}</span>
                            </td>
                        </tr>
                    </table>
                    <div style="background:#f9fafb;border-left:4px solid #e67e22;border-radius:0 8px 8px 0;padding:14px 18px;">
                        <p style="margin:0 0 6px;font-weight:600;color:#555;font-size:0.8em;text-transform:uppercase;letter-spacing:0.5px;">Descripción</p>
                        <p style="margin:0;color:#333;line-height:1.5;">{desc_txt}</p>
                    </div>
                </div>
                <div style="background:#f4f6fb;padding:14px 30px;text-align:center;font-size:12px;color:#999;">
                    Recordatorio automático — Este correo se envía diariamente hasta completar la tarea
                </div>
            </div>"""

            ok = enviar_email_gmail(
                t['asignado_email'],
                f"Recordatorio: {t['titulo']}",
                cuerpo_plano,
                html=cuerpo_html
            )
            if ok:
                enviados += 1
            else:
                errores += 1
                print(f"[ERROR] No se pudo enviar recordatorio de tarea #{t['id']} a {t['asignado_email']}")

        print(f"[OK] Recordatorios enviados: {enviados}, errores: {errores}")


if __name__ == '__main__':
    enviar_recordatorios()
