"""Private helpers for the proxy CLI; invoked through explicit subcommands."""
import sys

def reload_haproxy():
    """Validate configuration, then wait for the master to confirm a graceful reload."""
    import socket
    import subprocess

    config, endpoint = sys.argv[1:]
    subprocess.run(['/usr/sbin/haproxy', '-c', '-f', config], check=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(15)
        client.connect(endpoint)
        client.sendall(b'reload\n')
        result = bytearray()
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            result.extend(chunk)
            if len(result) > 1048576:
                raise SystemExit('HAProxy reload response exceeded limit')
    response = result.decode('utf-8', errors='replace')
    if response.splitlines()[:1] != ['Success=1']:
        print(response, file=sys.stderr)
        raise SystemExit('HAProxy did not confirm reload')
    print('HAProxy reload confirmed')
