import psycopg2
from app.database import get_db_connection

try:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'productos';")
    print(cur.fetchall())
except Exception as e:
    print(e)
