"""crm_service.py — funciones compartidas del CRM.

Provee upsert de contactos (por email o por nombre) y helpers reutilizables
desde fuera del blueprint CRM: formulario público, flujo de pago, quotes,
billing, etc.
"""
from flask import current_app as app
from database import get_db_cursor


def _clean(v, maxlen=200):
    if not v:
        return None
    s = str(v).strip()[:maxlen]
    return s or None


def upsert_contacto(
    *, email=None, nombre=None, telefono=None, empresa=None,
    ciudad=None, direccion=None, tipo='lead', origen=None,
    notas_append=None, tags_add=None,
):
    """Crea o actualiza un contacto CRM. Retorna el id del contacto.

    Matching: primero por email (case-insensitive). Si no hay email o no
    matchea, intenta por nombre exacto (case-insensitive). Si nada matchea,
    crea uno nuevo.

    En update, solo rellena campos que estén vacíos en el contacto actual
    (no pisa datos que el usuario ya ingresó manualmente), excepto:
      - notas_append: se concatena al final con un salto de línea
      - tags_add: se unen con los tags existentes sin duplicados
      - tipo: si el contacto es 'lead' y llega 'cliente', se promociona

    No lanza excepciones — loguea warning y retorna None si falla.
    """
    email = _clean(email)
    nombre = _clean(nombre)
    if not email and not nombre:
        return None

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            contacto = None
            if email:
                cur.execute(
                    "SELECT * FROM crm_contactos WHERE lower(email) = lower(%s) LIMIT 1",
                    (email,),
                )
                contacto = cur.fetchone()
            if not contacto and nombre:
                cur.execute(
                    "SELECT * FROM crm_contactos WHERE lower(nombre) = lower(%s) LIMIT 1",
                    (nombre,),
                )
                contacto = cur.fetchone()

            if contacto:
                # UPDATE solo campos vacíos
                updates = {}
                if not contacto.get('email') and email:
                    updates['email'] = email
                if not contacto.get('telefono') and telefono:
                    updates['telefono'] = _clean(telefono, 60)
                if not contacto.get('empresa') and empresa:
                    updates['empresa'] = _clean(empresa, 160)
                if not contacto.get('ciudad') and ciudad:
                    updates['ciudad'] = _clean(ciudad, 120)
                if not contacto.get('direccion') and direccion:
                    updates['direccion'] = _clean(direccion, 500)
                if not contacto.get('origen') and origen:
                    updates['origen'] = _clean(origen, 60)

                # Promoción lead → cliente
                if contacto.get('tipo') == 'lead' and tipo == 'cliente':
                    updates['tipo'] = 'cliente'

                # Append notas
                if notas_append:
                    existing = contacto.get('notas') or ''
                    nueva = (existing + '\n\n' + notas_append).strip() if existing else notas_append
                    updates['notas'] = nueva[:4000]

                if updates:
                    set_clause = ', '.join(f"{k} = %s" for k in updates)
                    cur.execute(
                        f"UPDATE crm_contactos SET {set_clause}, updated_at = NOW() WHERE id = %s",
                        (*updates.values(), contacto['id']),
                    )

                # Tags additive
                if tags_add:
                    cur.execute(
                        """UPDATE crm_contactos
                              SET tags = ARRAY(SELECT DISTINCT unnest(COALESCE(tags,'{}') || %s::text[]))
                            WHERE id = %s""",
                        (list(tags_add), contacto['id']),
                    )
                return contacto['id']

            # INSERT nuevo
            cur.execute(
                """INSERT INTO crm_contactos
                       (tipo, nombre, empresa, email, telefono, ciudad,
                        direccion, origen, notas, tags, activo)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)
                   RETURNING id""",
                (
                    tipo,
                    nombre or (email.split('@')[0] if email else 'Sin nombre'),
                    _clean(empresa, 160),
                    email,
                    _clean(telefono, 60),
                    _clean(ciudad, 120),
                    _clean(direccion, 500),
                    _clean(origen, 60),
                    _clean(notas_append, 4000),
                    list(tags_add or []),
                ),
            )
            return cur.fetchone()['id']
    except Exception as e:
        try:
            app.logger.warning(f"upsert_contacto falló: {e}")
        except Exception:
            pass
        return None


def registrar_actividad(contacto_id, tipo, asunto=None, descripcion=None,
                         usuario_id=None, fecha_actividad=None):
    """Agrega una actividad al contacto. No lanza excepciones."""
    if not contacto_id or not tipo:
        return
    try:
        with get_db_cursor() as cur:
            if fecha_actividad:
                cur.execute(
                    """INSERT INTO crm_actividades
                           (contacto_id, tipo, asunto, descripcion, fecha_actividad, usuario_id)
                       VALUES (%s,%s,%s,%s,%s,%s)""",
                    (contacto_id, tipo, _clean(asunto, 200),
                     _clean(descripcion, 4000), fecha_actividad, usuario_id),
                )
            else:
                cur.execute(
                    """INSERT INTO crm_actividades
                           (contacto_id, tipo, asunto, descripcion, usuario_id, fecha_actividad)
                       VALUES (%s,%s,%s,%s,%s, NOW())""",
                    (contacto_id, tipo, _clean(asunto, 200),
                     _clean(descripcion, 4000), usuario_id),
                )
    except Exception as e:
        try:
            app.logger.warning(f"registrar_actividad falló: {e}")
        except Exception:
            pass


def sync_oportunidad_cotizacion(cotizacion_id, *, titulo=None, monto=None,
                                  contacto_id=None, etapa='propuesta',
                                  motivo_perdida=None, usuario_id=None):
    """Upsert de oportunidad vinculada a una cotización.

    Busca por `cotizacion_id`. Si existe actualiza etapa/monto/título.
    Si no existe y hay `contacto_id`, la crea en etapa `propuesta` por defecto.
    """
    if not cotizacion_id:
        return None
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(
                "SELECT id FROM crm_oportunidades WHERE cotizacion_id = %s LIMIT 1",
                (cotizacion_id,),
            )
            row = cur.fetchone()
            if row:
                sets = ['etapa = %s', 'updated_at = NOW()']
                vals = [etapa]
                if titulo:
                    sets.append('titulo = %s')
                    vals.append(_clean(titulo, 200))
                if monto is not None:
                    sets.append('monto_estimado = %s')
                    vals.append(float(monto))
                if etapa == 'ganada':
                    sets.append('fecha_cierre_real = CURRENT_DATE')
                    sets.append('probabilidad = 100')
                if etapa == 'perdida':
                    sets.append('fecha_cierre_real = CURRENT_DATE')
                    sets.append('probabilidad = 0')
                    if motivo_perdida:
                        sets.append('motivo_perdida = %s')
                        vals.append(_clean(motivo_perdida, 160))
                vals.append(row['id'])
                cur.execute(
                    f"UPDATE crm_oportunidades SET {', '.join(sets)} WHERE id = %s",
                    tuple(vals),
                )
                return row['id']

            if not contacto_id:
                return None
            cur.execute(
                """INSERT INTO crm_oportunidades
                       (contacto_id, titulo, monto_estimado, probabilidad, etapa,
                        fuente, cotizacion_id, asignado_a)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   RETURNING id""",
                (contacto_id, _clean(titulo, 200) or f"Cotización #{cotizacion_id}",
                 float(monto or 0), 60, etapa, 'cotizacion',
                 cotizacion_id, usuario_id),
            )
            return cur.fetchone()['id']
    except Exception as e:
        try:
            app.logger.warning(f"sync_oportunidad_cotizacion falló: {e}")
        except Exception:
            pass
        return None
