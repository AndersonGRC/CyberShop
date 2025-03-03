# database.py
import psycopg2

def get_db_connection():
    try:
        conn = psycopg2.connect(
            dbname="cybershop",
            user="postgres",
            password="Omegafito7217*",
            host="localhost",
            port="5432"
        )
        print("Conexión exitosa a la base de datos 'cybershop'")  # Depuración
        return conn
    except Exception as e:
        print("Error al conectar a la base de datos:", e)  # Depuración
        raise e