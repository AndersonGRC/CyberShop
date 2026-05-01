
import psycopg2
from app.database import get_db_connection

def run_sql_file(filename):
    print(f"Executing {filename}...")
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            sql = f.read()
            cur.execute(sql)
        conn.commit()
        print(f"Successfully executed {filename}")
    except Exception as e:
        conn.rollback()
        print(f"Error executing {filename}: {e}")
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    print("Initializing Billing Module Database...")
    run_sql_file('app/schema_cuentas_cobro.sql')
    print("Database initialization complete.")
