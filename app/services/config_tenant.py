"""Escritura tolerante en las tablas de configuración del cliente.

POR QUÉ EXISTE (hallazgo 2026-09-21): no todas las BD de clientes tienen la
restricción única sobre `clave`. En las que no la tienen, cualquier
`INSERT ... ON CONFLICT (clave)` falla con:

    there is no unique or exclusion constraint matching the ON CONFLICT specification

y la función que lo usaba dejaba de guardar (a veces en silencio, porque el
error iba dentro de un try/except). Estos helpers hacen UPDATE y, solo si no
existía la fila, INSERT: funcionan igual con o sin la restricción.

Se usan con un cursor ya abierto, para respetar la transacción de quien llama.
"""


def set_cliente_config(cur, clave, valor, tipo='texto', grupo='sistema',
                       descripcion=None, orden=None, actualizar_meta=False):
    """Guarda una clave de `cliente_config`. Por defecto solo toca el valor:
    así no se pisan el tipo/grupo/descripción que ya tenga la fila."""
    if actualizar_meta:
        cur.execute("""UPDATE cliente_config
                       SET valor = %s, tipo = %s, grupo = %s, descripcion = %s
                       WHERE clave = %s""", (valor, tipo, grupo, descripcion, clave))
    else:
        cur.execute("UPDATE cliente_config SET valor = %s WHERE clave = %s", (valor, clave))
    if cur.rowcount:
        if orden is not None:
            cur.execute("UPDATE cliente_config SET orden = %s WHERE clave = %s", (orden, clave))
        return False                      # ya existía: se actualizó
    if orden is not None:
        cur.execute("""INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (clave, valor, tipo, grupo, descripcion, orden))
    else:
        cur.execute("""INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion)
                       VALUES (%s, %s, %s, %s, %s)""", (clave, valor, tipo, grupo, descripcion))
    return True                           # se creó


def set_config_seccion(cur, clave, valor, descripcion=None):
    """Igual que set_cliente_config pero para `config_secciones`."""
    cur.execute("UPDATE config_secciones SET valor = %s, descripcion = %s WHERE clave = %s",
                (valor, descripcion, clave))
    if cur.rowcount:
        return False
    cur.execute("INSERT INTO config_secciones (clave, valor, descripcion) VALUES (%s, %s, %s)",
                (clave, valor, descripcion))
    return True
