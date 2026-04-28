#!/usr/bin/env python3
"""HANA baseline checker: lista tablas, columnas y muestra filas.
Ejecuta desde el venv con hdbcli instalado.
"""
import os

# Read .env manually without dotenv dependency
env_file = '.env'
if os.path.exists(env_file):
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                os.environ[key.strip()] = val.strip()

HANA_HOST = os.getenv('HANA_HOST')
HANA_PORT = int(os.getenv('HANA_PORT', '443'))
HANA_USER = os.getenv('HANA_USER')
HANA_PASSWORD = os.getenv('HANA_PASSWORD')
HANA_SCHEMA = os.getenv('HANA_SCHEMA', 'SOC_PIPELINE')

TABLES = [
    'RAW_LOGS', 'INGEST_RUNS', 'WINDOW_FEATURES', 'WINDOW_METRICS', 'ALERTS_EVENTS',
    'MODEL_RUNS', 'MODEL_PREDICTIONS', 'FEATURE_DEFINITIONS', 'ALERT_FEEDBACK', 'MODEL_SCORES'
]

try:
    from hdbcli import dbapi
except Exception as e:
    print('El paquete hdbcli no está instalado. Instálalo con:')
    print('  python -m pip install -r requirements-hana.txt')
    raise

conn = None
try:
    print('Conectando a HANA %s:%s como %s (schema %s)' % (HANA_HOST, HANA_PORT, HANA_USER, HANA_SCHEMA))
    conn = dbapi.connect(address=HANA_HOST, port=HANA_PORT, user=HANA_USER, password=HANA_PASSWORD, encrypt=True, sslValidateCertificate=False)
    cur = conn.cursor()

    # List tables existence
    for t in TABLES:
        q = "SELECT COUNT(*) FROM SYS.TABLES WHERE SCHEMA_NAME = '%s' AND TABLE_NAME = '%s'" % (HANA_SCHEMA, t)
        try:
            cur.execute(q)
            exists = cur.fetchone()[0] > 0
        except Exception as e:
            print('Error comprobando existencia de %s: %s' % (t, e))
            exists = False
        print('\n==> Table %s: %s' % (t, 'FOUND' if exists else 'MISSING'))
        if exists:
            # columns
            try:
                cur.execute("SELECT COLUMN_NAME, DATA_TYPE_NAME, LENGTH FROM SYS.TABLE_COLUMNS WHERE SCHEMA_NAME = '%s' AND TABLE_NAME = '%s' ORDER BY POSITION" % (HANA_SCHEMA, t))
                cols = cur.fetchall()
                print(' Columns:')
                for c in cols:
                    print('  - %s: %s(%s)' % (c[0], c[1], c[2]))
            except Exception as e:
                print('  Error leyendo columnas: %s' % e)

            # sample rows (safe TOP 5)
            try:
                sample_sql = 'SELECT TOP 5 * FROM "{schema}"."{table}"'.format(schema=HANA_SCHEMA, table=t)
                cur.execute(sample_sql)
                rows = cur.fetchall()
                print(' Sample rows (up to 5): %s' % (len(rows),))
                for r in rows:
                    print('  -', r)
            except Exception as e:
                print('  Error sample rows: %s' % e)

            # try a COUNT(*) but guard exceptions (may be heavy)
            try:
                cur.execute('SELECT COUNT(*) FROM "{schema}"."{table}"'.format(schema=HANA_SCHEMA, table=t))
                cnt = cur.fetchone()[0]
                print(' Row count:', cnt)
            except Exception as e:
                print('  Skipping COUNT(*) due to error/cost: %s' % e)

    # Optional: run an EXPLAIN plan for a representative query on WINDOW_METRICS
    try:
        explain_sql = 'EXPLAIN PLAN FOR SELECT TOP 100 * FROM "{schema}"."WINDOW_METRICS" WHERE "EVENT_TIME" >= ADD_SECONDS(CURRENT_TIMESTAMP, -3600) ORDER BY "EVENT_TIME" DESC'.format(schema=HANA_SCHEMA)
        print('\nRunning:', explain_sql)
        cur.execute(explain_sql)
        # Try to fetch plan rows from SYS.EXPLAIN_PLAN_TABLE (best-effort)
        try:
            cur.execute('SELECT * FROM "SYS"."EXPLAIN_PLAN_TABLE" ORDER BY START_TIME DESC')
            plan_rows = cur.fetchall()
            print(' Explain plan rows sample:', len(plan_rows))
            for pr in plan_rows[:10]:
                print('  -', pr)
        except Exception as e:
            print(' Could not fetch explain plan table: %s' % e)
    except Exception as e:
        print('Skipping EXPLAIN due to error: %s' % e)

except Exception as e:
    print('Error de conexión o ejecución:', e)
finally:
    if conn:
        conn.close()
    print('\nDone')
