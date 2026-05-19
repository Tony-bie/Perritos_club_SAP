from hdbcli import dbapi
import os
import traceback
import socket

# Configurable via environment for quick diagnostics
host = os.getenv('HANA_HOST')
port = int(os.getenv('HANA_PORT', '443'))
user = os.getenv('HANA_USER')
password = os.getenv('HANA_PASSWORD')

# Controls: HANA_ENCRYPT (True/False), HANA_SSL_VALIDATE_CERT (True/False), HANA_TIMEOUT (seconds)
encrypt = os.getenv('HANA_ENCRYPT', 'False').lower() in ('1', 'true', 'yes')
ssl_validate = os.getenv('HANA_SSL_VALIDATE_CERT', 'False').lower() in ('1', 'true', 'yes')
timeout = int(os.getenv('HANA_TIMEOUT', '5'))

print('Testing HANA host:', host, 'port:', port, 'encrypt=', encrypt, 'sslValidateCertificate=', ssl_validate, 'timeout=', timeout)

socket.setdefaulttimeout(timeout)

try:
    conn = dbapi.connect(
        address=host,
        port=port,
        user=user,
        password=password,
        encrypt=encrypt,
        sslValidateCertificate=ssl_validate,
    )
    print('Connected successfully')
    conn.close()
except Exception as e:
    print('Connection failed:', type(e), e)
    traceback.print_exc()
