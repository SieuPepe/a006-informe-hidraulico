"""
Módulo de conexión a PostgreSQL/Giswater.
"""
import psycopg2
import psycopg2.extras
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_SCHEMA


def get_connection():
    """Abre y devuelve una conexión a PostgreSQL."""
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        options=f"-c search_path={DB_SCHEMA},public"
    )
    return conn


def execute_query(sql, params=None):
    """
    Ejecuta una consulta y devuelve los resultados como lista de dicts.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def execute_scalar(sql, params=None):
    """
    Ejecuta una consulta y devuelve un único valor escalar.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()


def test_connection():
    """Verifica que la conexión funciona correctamente."""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            version = cur.fetchone()[0]
        conn.close()
        print(f"  Conexión OK: {version[:60]}")
        return True
    except Exception as e:
        print(f"  Error de conexión: {e}")
        return False
