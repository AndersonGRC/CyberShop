"""Métodos de pago de la tienda: UNA sola lista para el POS y el cobro de mesas.

El dueño la configura en el POS («Configurar métodos de pago», tabla
`metodos_pago_pos`): Efectivo, Nequi, Daviplata, Tarjeta… con su color e ícono.
Si la tabla no existe se crea y se siembra con los 6 de siempre.

Solo `EFECTIVO` cuenta como efectivo en el arqueo de caja (routes/caja.py); el
resto entra como pago digital.
"""

from flask import current_app

from database import get_db_cursor

# (código, nombre, color, ícono Font Awesome, orden)
METODOS_PAGO_DEFAULT = [
    ('EFECTIVO',      'Efectivo',      '#16a34a', 'fa-money-bill-wave', 10),
    ('NEQUI',         'Nequi',         '#7c3aed', 'fa-mobile-alt',      20),
    ('TARJETA',       'Tarjeta',       '#2563eb', 'fa-credit-card',     30),
    ('TRANSFERENCIA', 'Transferencia', '#0d9488', 'fa-exchange-alt',    40),
    ('DAVIPLATA',     'Daviplata',     '#dc2626', 'fa-wallet',          50),
    ('OTRO',          'Otro',          '#64748b', 'fa-ellipsis-h',      60),
]


def asegurar_tabla(cur):
    """Crea la tabla de métodos de pago y la siembra con los 6 por defecto si
    está vacía (preserva el comportamiento previo)."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS metodos_pago_pos (
            id      SERIAL PRIMARY KEY,
            codigo  VARCHAR(30)  NOT NULL,
            nombre  VARCHAR(50)  NOT NULL,
            color   VARCHAR(20)  NOT NULL DEFAULT '#64748b',
            icono   VARCHAR(40)  NOT NULL DEFAULT 'fa-money-bill-wave',
            orden   INTEGER      NOT NULL DEFAULT 0,
            activo  BOOLEAN      NOT NULL DEFAULT TRUE
        )
    """)
    cur.execute("SELECT COUNT(*) FROM metodos_pago_pos")
    if (cur.fetchone()[0] or 0) == 0:
        for codigo, nombre, color, icono, orden in METODOS_PAGO_DEFAULT:
            cur.execute(
                "INSERT INTO metodos_pago_pos (codigo, nombre, color, icono, orden) "
                "VALUES (%s, %s, %s, %s, %s)",
                (codigo, nombre, color, icono, orden),
            )


def listar(solo_activos=True):
    """Métodos de pago del tenant (crea/siembra la tabla si hace falta)."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            asegurar_tabla(cur)
            q = "SELECT id, codigo, nombre, color, icono, orden, activo FROM metodos_pago_pos"
            if solo_activos:
                q += " WHERE activo = TRUE"
            q += " ORDER BY orden, id"
            cur.execute(q)
            return cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning('metodos_pago fallback: %s', exc)
        return [
            {'id': None, 'codigo': c, 'nombre': n, 'color': col, 'icono': ic, 'orden': o, 'activo': True}
            for (c, n, col, ic, o) in METODOS_PAGO_DEFAULT
        ]


def nombres():
    """{código: nombre} de TODOS los métodos (también los apagados), para
    mostrar ventas viejas con su nombre."""
    return {m['codigo']: m['nombre'] for m in listar(solo_activos=False)}
