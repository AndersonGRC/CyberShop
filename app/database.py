import os
# database.py
import psycopg2

def get_db_connection():
    try:
        conn = psycopg2.connect(
            dbname=os.getenv('DB_NAME', 'achirasdemitierra'),
            user=os.getenv('DB_USER', 'postgres'),
            password=os.getenv('DB_PASSWORD', ''),
            host=os.getenv('DB_HOST', 'localhost'),
            port=os.getenv('DB_PORT', '5432')
        )
        print("Conexión exitosa a la base de datos 'achirasdemitierra'")  # Depuración
        return conn
    except Exception as e:
        print("Error al conectar a la base de datos:", e)  # Depuración
        raise e