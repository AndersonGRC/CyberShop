import psycopg2

def get_db_connection():
    """
    Establece y retorna una conexión a la base de datos PostgreSQL.
    """
    conn = psycopg2.connect(
        dbname="cybershop",      # Nombre de la base de datos
        user="postgres",         # Usuario de la base de datos
        password="Omegafito7217*",  # Contraseña del usuario
        host="localhost",        # Host de la base de datos
        port="5432"              # Puerto de la base de datos
    )
    return conn