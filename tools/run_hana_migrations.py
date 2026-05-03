"""Script to run HANA SQL migration files and call cleanup procedure.
Usage (example):

HANA_HOST=... HANA_PORT=443 HANA_USER=... HANA_PASSWORD=... HANA_SCHEMA=SOC_PIPELINE \
    c:/Users/Lenovo/Perritos_club_SAP/.venv/Scripts/python.exe tools/run_hana_migrations.py

The script reads env vars and executes sql/migrations/004_retention.sql and sql/migrations/999_validate_block_b.sql
then calls the cleanup procedure with p_retention_days=999 (dry-run/validation) and prints results.
"""
import os
import sys
from hdbcli import dbapi

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MIG_004 = os.path.join(ROOT, 'sql', 'migrations', '004_retention.sql')
MIG_999 = os.path.join(ROOT, 'sql', 'migrations', '999_validate_block_b.sql')

HOST = os.environ.get('HANA_HOST')
PORT = int(os.environ.get('HANA_PORT', '443'))
USER = os.environ.get('HANA_USER')
PASSWORD = os.environ.get('HANA_PASSWORD')
SCHEMA = os.environ.get('HANA_SCHEMA')

if not all([HOST, PORT, USER, PASSWORD]):
    print('Missing HANA connection env vars. Set HANA_HOST, HANA_PORT, HANA_USER, HANA_PASSWORD')
    sys.exit(2)

encrypt = True if PORT == 443 else False

def exec_file(cur, path):
    print('\n--- Executing', path)
    with open(path, 'r', encoding='utf-8') as f:
        sql = f.read()
    try:
        cur.execute(sql)
        print('Executed file as single statement')
    except Exception as e:
        print('Single execute failed:', e)
        # Try split by statement terminator ';' — best-effort
        parts = [p.strip() for p in sql.split(';') if p.strip()]
        for i, stmt in enumerate(parts, 1):
            try:
                cur.execute(stmt)
                print(f'  stmt {i} ok')
            except Exception as e2:
                print(f'  stmt {i} failed:', str(e2)[:200])


def main():
    conn = None
    try:
        conn = dbapi.connect(address=HOST, port=PORT, user=USER, password=PASSWORD, encrypt=encrypt)
        cur = conn.cursor()
        if SCHEMA:
            cur.execute(f'SET SCHEMA "{SCHEMA}"')
            print('Schema set to', SCHEMA)

        for path in (MIG_004, MIG_999):
            if not os.path.exists(path):
                print('Migration file not found:', path)
                continue
            exec_file(cur, path)
            conn.commit()

        # Call cleanup procedure with p_retention_days => 999 (validation call)
        print('\n--- Calling cleanup procedure')
        try:
            call_sql = f'CALL "{SCHEMA}"."sp_cleanup_old_data"(p_retention_days => ? )'
            # hdbcli supports positional parameters; we'll pass 999
            cur.execute(call_sql, (999,))
            # Try fetch all result sets if any
            try:
                rows = cur.fetchall()
                print('Procedure returned rows:', rows)
            except Exception:
                print('Procedure call completed (no resultset or not fetchable)')
            conn.commit()
        except Exception as e:
            print('Procedure call failed, trying without named param...', e)
            try:
                cur.execute(f'CALL "{SCHEMA}"."sp_cleanup_old_data"(999)')
                try:
                    rows = cur.fetchall()
                    print('Procedure returned rows:', rows)
                except Exception:
                    print('Procedure call completed (no resultset or not fetchable)')
                conn.commit()
            except Exception as e2:
                print('Procedure call (positional) failed:', e2)

    except Exception as e:
        print('Connection error:', e)
        sys.exit(3)
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    main()
