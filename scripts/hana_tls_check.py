import socket, ssl, os, pprint, traceback

host = os.getenv('HANA_HOST')
port = int(os.getenv('HANA_PORT', '443'))
timeout = int(os.getenv('HANA_TIMEOUT', '5'))

print('TLS probe to', host, 'port', port, 'timeout', timeout)

context = ssl.create_default_context()
# Don't fail for untrusted certs; we only want handshake info
context.check_hostname = False
context.verify_mode = ssl.CERT_NONE

try:
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with context.wrap_socket(sock, server_hostname=host) as ssock:
            print('TLS protocol:', ssock.version())
            print('Cipher:', ssock.cipher())
            cert = ssock.getpeercert()
            print('Peer cert:')
            pprint.pprint(cert)
except Exception as e:
    print('TLS probe failed:', type(e), e)
    traceback.print_exc()
