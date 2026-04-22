"""Script de prueba para verificar conexión a SAP HANA desde el repo.

Uso:
  - Rellena .env con variables HANA (HANA_HOST, HANA_PORT, HANA_USER, HANA_PASSWORD, HANA_SCHEMA)
  - Ejecuta: python test_hana_connection.py
"""
from __future__ import annotations

import sys
from config import load_settings


def main() -> int:
    settings = load_settings()

    host = settings.hana_host
    port = settings.hana_port
    user = settings.hana_user
    schema = settings.hana_schema

    if not host or not user:
        print("Faltan variables HANA_HOST o HANA_USER en el entorno. Edita .env o exporta las variables.")
        return 2

    print("HANA settings:", {"host": host, "port": port, "user": user, "schema": schema})

    try:
        from hdbcli import dbapi  # type: ignore
    except Exception as exc:
        print("El paquete hdbcli no está instalado. Instálalo con:")
        print("  python -m pip install -r requirements-hana.txt")
        print("Error:", exc)
        return 3

    try:
        print("Intentando conectar a HANA...")
        conn = dbapi.connect(
            address=host,
            port=port,
            user=user,
            password=settings.hana_password,
            encrypt="true",
            sslValidateCertificate="true",
        )
        cursor = conn.cursor()
        cursor.execute("SELECT CURRENT_UTCTIMESTAMP FROM DUMMY")
        row = cursor.fetchone()
        print("Conexión exitosa. Hora DB (UTC):", row[0] if row else None)
        cursor.close()
        conn.close()
    except Exception as exc:
        print("Falló la conexión a HANA:", exc)
        return 4

    print("Prueba completada correctamente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
