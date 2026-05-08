import os
from hdbcli import dbapi

RUN_ID = '830053ad-df7c-4841-9af7-65839e543c49'
SCHEMA = 'SOC_PIPELINE'

conn = dbapi.connect(
    address=os.environ['HANA_HOST'],
    port=int(os.environ['HANA_PORT']),
    user=os.environ['HANA_USER'],
    password=os.environ['HANA_PASSWORD'],
    encrypt=True,
)
cur = conn.cursor()
cur.execute(f'SET SCHEMA "{SCHEMA}"')
queries = [
    ('INGEST_RUNS', 'SELECT COUNT(*) FROM "SOC_PIPELINE"."INGEST_RUNS" WHERE "RUN_ID" = ?', (RUN_ID,)),
    ('RAW_LOGS', 'SELECT COUNT(*) FROM "SOC_PIPELINE"."RAW_LOGS" WHERE "INGESTED_AT" IS NOT NULL', ()),
    ('WINDOW_METRICS', 'SELECT COUNT(*) FROM "SOC_PIPELINE"."WINDOW_METRICS" WHERE "RUN_ID" = ?', (RUN_ID,)),
    ('WINDOW_METRICS_TOTAL', 'SELECT COUNT(*) FROM "SOC_PIPELINE"."WINDOW_METRICS"', ()),
    ('ALERTS_EVENTS', 'SELECT COUNT(*) FROM "SOC_PIPELINE"."ALERTS_EVENTS" WHERE "RUN_ID" = ?', (RUN_ID,)),
]
for table, sql, params in queries:
    cur.execute(sql, params)
    print(f'{table}={cur.fetchone()[0]}')

cur.execute('SELECT "WINDOW_KEY" FROM "SOC_PIPELINE"."WINDOW_METRICS" ORDER BY "SAVED_AT_UTC" DESC LIMIT 1')
row = cur.fetchone()
print(f'WINDOW_METRICS_LATEST={row[0] if row else "<none>"}')
conn.close()
