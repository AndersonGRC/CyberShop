import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))
from database import get_db_connection

def main():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden) VALUES
    ('color_precio_producto', '#091C5A', 'color', 'colores', 'Color precio del producto', 20),
    ('color_boton_producto', '#091C5A', 'color', 'colores', 'Fondo botón producto', 21),
    ('color_boton_producto_hover', '#05103a', 'color', 'colores', 'Hover botón producto', 22),
    ('color_alerta_confirmar_hover', '#05103a', 'color', 'colores', 'Hover aceptar alerta', 23)
    ON CONFLICT (clave) DO NOTHING;
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("Variables CSS añadidas")

if __name__ == "__main__":
    main()
