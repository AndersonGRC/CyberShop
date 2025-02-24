import psycopg2

def get_db_connection():
    conn = psycopg2.connect(
        dbname="cybershop",
        user="cybershopuser",
        password="Omegafito7217*",
        host="localhost",
        port="5432"
    )
    return conn