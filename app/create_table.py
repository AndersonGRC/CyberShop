import psycopg2

try:
    conn = psycopg2.connect(dbname='cybershop', user='postgres', password='Omegafito7217*', host='localhost', port='5432')
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventario_log (
            id SERIAL PRIMARY KEY,
            producto_id INT REFERENCES productos(id),
            tipo VARCHAR(20),
            cantidad INT,
            stock_anterior INT,
            stock_nuevo INT,
            motivo TEXT,
            usuario_id INT REFERENCES usuarios(id),
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cur.close()
    conn.close()
    print('Table created successfully')
except Exception as e:
    print(f"Error: {e}")
