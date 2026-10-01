"""Relleno único: pasa al CRM las pruebas gratis registradas ANTES de que el
registro las creara solo (contacto lead con WhatsApp y correo).

- Idempotente: solo crea el contacto si ese correo aún no está en el CRM; no
  modifica ni borra nada existente.
- Sin --aplicar solo muestra lo que haría (no escribe).

Uso (en la carpeta app, con la BD de CyberShop):
    python tools/backfill_crm_pruebas.py            # vista previa
    python tools/backfill_crm_pruebas.py --aplicar  # escribe
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_db_cursor  # noqa: E402
from services.crm_pruebas_service import registrar_interesado  # noqa: E402


def main(aplicar=False):
    creados, ya_estaban = [], 0
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT to_regclass('crm_contactos') IS NOT NULL AS crm, "
                    "to_regclass('plan_compras') IS NOT NULL AS pc")
        f = cur.fetchone()
        if not (f['crm'] and f['pc']):
            print('Esta BD no tiene CRM o plan_compras: nada que hacer.')
            return
        cur.execute("""SELECT buyer_nombre, buyer_email, buyer_telefono, nombre_negocio, slug
                       FROM plan_compras
                       WHERE referencia_pedido LIKE 'TRIAL-%%' AND renovacion_de IS NULL
                       ORDER BY id""", ())
        pruebas = cur.fetchall()
        for p in pruebas:
            cur.execute('SELECT 1 FROM crm_contactos WHERE LOWER(email) = LOWER(%s)', (p['buyer_email'],))
            if cur.fetchone():
                ya_estaban += 1
                continue
            creados.append(p['buyer_email'])
            if aplicar:
                registrar_interesado(cur, nombre=p['buyer_nombre'], email=p['buyer_email'],
                                     telefono=p['buyer_telefono'] or '', negocio=p['nombre_negocio'],
                                     slug=p['slug'])
        if not aplicar:
            cur.connection.rollback()
    accion = 'Creados' if aplicar else 'Se crearían'
    print(f'Pruebas: {len(pruebas)} · ya estaban en el CRM: {ya_estaban} · {accion}: {len(creados)}')
    for email in creados:
        print('  -', email)


if __name__ == '__main__':
    main(aplicar='--aplicar' in sys.argv)
