"""Private helpers for the proxy CLI; invoked through explicit subcommands."""
import sys

def verify():
    """Acceptance checks for the installed proxy. Usage: proxy verify [on|off]."""
    import concurrent.futures
    import json
    import os
    import shutil
    from pathlib import Path
    import subprocess
    import sys
    import time

    home = Path.home()
    project = Path(__file__).resolve().parent.parent
    expected = sys.argv[1] if len(sys.argv) > 1 else None
    if len(sys.argv) > 2 or expected not in (None, 'on', 'off'):
        raise SystemExit('Usage: proxy verify [on|off]')
    logs = project / 'logs/acceptance' / time.strftime('%Y%m%d-%H%M%S')
    logs.mkdir(parents=True, exist_ok=True)
    results = {}
    ca = Path(os.environ.get('PROXY_CA_BUNDLE') or '/etc/ssl/certs/ca-certificates.crt')
    public_image = 'registry.suse.com/bci/bci-base:15.7'
    corporate_image = 'docker.nexus.secdmz.nav.gov.hu/nav-builder/suse:0.3.0'

    def record(name, ok, output, code=0):
        (logs / (name + '.log')).write_text(output)
        results[name] = {'passed': ok, 'exit_code': code}
        print(('PASS ' if ok else 'FAIL ') + name, flush=True)
        return ok, output

    def run(name, cmd, env=None, timeout=60):
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout, cwd=logs)
            return record(name, p.returncode == 0, p.stdout + p.stderr, p.returncode)
        except subprocess.TimeoutExpired as exc:
            def text(value):
                return value.decode(errors='replace') if isinstance(value, bytes) else (value or '')
            return record(name, False, text(exc.stdout) + text(exc.stderr) + '\nTimed out\n', 124)
        except OSError as exc:
            return record(name, False, str(exc) + '\n', 127)

    ok, status = run('state', [str(project / 'proxy'), 'status'])
    state = dict(line.split(': ', 1) for line in status.splitlines() if ': ' in line)
    record('expected-auto-route', ok and state.get('mode') == 'auto' and state.get('pending') == 'none'
           and (expected is None or state.get('route') == expected), status)
    print('Automatic route:', state.get('route'), flush=True)
    run('services', ['systemctl', '--user', 'is-active', 'proxy-endpoint.service', 'proxy-direct.service', 'proxy-monitor.service'])
    run('enabled', ['systemctl', '--user', 'is-enabled', 'proxy-endpoint.service', 'proxy-direct.service', 'proxy-monitor.service'])
    for scheme in ['http', 'https']:
        run('host-' + scheme, ['curl', '--silent', '--show-error', '--fail', '--max-time', '20', '--noproxy', '',
                              '--proxy', 'http://127.0.0.1:18080', scheme + '://example.com', '-o', '/dev/null'])
    clean = dict(os.environ)
    for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'NO_PROXY', 'no_proxy']:
        clean.pop(key, None)
    run('fresh-zsh', ['/usr/bin/zsh', '-i', '-c', '[[ $HTTP_PROXY == http://127.0.0.1:18080 && $HTTPS_PROXY == $HTTP_PROXY ]] && curl --silent --show-error --fail --max-time 20 https://example.com -o /dev/null'], env=clean)

    def apt_check(label, ubuntu_only=False):
        folder = logs / label
        for directory in ['lists/partial', 'cache/archives/partial', 'log']:
            (folder / directory).mkdir(parents=True, exist_ok=True)
        config = folder / 'validation.conf'
        # Disable administrative update hooks; preserve configured proxy and trust checks.
        config.write_text('#clear APT::Update::Post-Invoke;\n#clear APT::Update::Post-Invoke-Success;\n#clear DPkg::Post-Invoke;\n')
        cmd = ['apt-get', '-c', str(config), '-o', 'Dir::State::lists=' + str(folder / 'lists'),
               '-o', 'Dir::Cache=' + str(folder / 'cache'), '-o', 'Dir::Log=' + str(folder / 'log'),
               '-o', 'Debug::NoLocking=1', '-o', 'APT::Get::List-Cleanup=0', '-o', 'APT::Update::Error-Mode=any',
               '-o', 'Acquire::Retries=0', '-o', 'Acquire::http::Timeout=20', '-o', 'Acquire::https::Timeout=20']
        if ubuntu_only:
            sources = folder / 'ubuntu.list'
            sources.write_text('deb http://archive.ubuntu.com/ubuntu noble main\ndeb http://security.ubuntu.com/ubuntu noble-security main\n')
            cmd += ['-o', 'Dir::Etc::sourcelist=' + str(sources), '-o', 'Dir::Etc::sourceparts=-']
        return run(label, cmd + ['update'], env=clean, timeout=240)

    def docker_checks(label, image):
        run('pull-' + label, ['docker', 'pull', image], timeout=240)
        context = logs / ('build-' + label)
        context.mkdir()
        # A read-only build-context mount supplies trust without adding it to an image layer.
        # The bundle exceeds BuildKit's secret-size limit; it contains public certificates.
        shutil.copyfile(ca, context / 'proxy-ca.pem')
        checks = ('test "$HTTP_PROXY" = "http://192.168.20.5:18080" && '
                  'test "$HTTPS_PROXY" = "$HTTP_PROXY" && '
                  'test "$http_proxy" = "$HTTP_PROXY" && '
                  'test "$https_proxy" = "$HTTPS_PROXY" && '
                  'curl --silent --show-error --fail --max-time 25 http://example.com -o /dev/null && '
                  'curl --cacert /run/proxy-ca.pem --silent --show-error --fail --max-time 25 https://example.com -o /dev/null')
        (context / 'Dockerfile').write_text('FROM ' + image + '\nRUN --mount=type=bind,source=proxy-ca.pem,target=/run/proxy-ca.pem ' + checks + '\n')
        iidfile = context / 'image-id'
        run('build-' + label, ['docker', 'build', '--no-cache', '--progress=plain',
                              '--iidfile', str(iidfile), str(context)], timeout=300)
        if iidfile.is_file():
            iid = iidfile.read_text().strip()
            if iid.startswith('sha256:') and len(iid) == 71:
                run('cleanup-build-' + label, ['docker', 'image', 'rm', '--no-prune', iid])

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(apt_check, 'apt-configured'), pool.submit(apt_check, 'apt-ubuntu', True),
                pool.submit(docker_checks, 'public', public_image)]
        if state.get('route') == 'on':
            jobs.append(pool.submit(docker_checks, 'corporate', corporate_image))
        else:
            print('SKIP corporate image pull/build: corporate route is not selected', flush=True)
        for job in concurrent.futures.as_completed(jobs):
            job.result()

    for network in ['bridge', 'opencode_gitlab_mcp_net']:
        checks = ('test "$HTTP_PROXY" = "http://192.168.20.5:18080" && test "$HTTPS_PROXY" = "$HTTP_PROXY" && '
                  'curl --cacert /tmp/proxy-ca.pem --silent --show-error --fail --max-time 20 https://example.com -o /dev/null')
        run('container-' + network, ['docker', 'run', '--rm', '--pull=never', '--network', network, '--mount',
                                     f'type=bind,src={ca},dst=/tmp/proxy-ca.pem,readonly', public_image, 'sh', '-c', checks])
    env = dict(os.environ, HTTP_PROXY='http://127.0.0.1:18080', HTTPS_PROXY='http://127.0.0.1:18080',
               http_proxy='http://127.0.0.1:18080', https_proxy='http://127.0.0.1:18080',
               NO_PROXY='localhost,127.0.0.1,::1', no_proxy='localhost,127.0.0.1,::1',
               SSL_CERT_FILE=str(ca), REQUESTS_CA_BUNDLE=str(ca), OPENCODE_PERMISSION='{"*":"deny"}')
    ok, out = run('authenticated-stream', ['/home/linuxbrew/.linuxbrew/bin/opencode', 'run', '--pure', '--format', 'json',
                                         '--title', 'Installed proxy acceptance check',
                                         'Reply with exactly PROXY_ACCEPTANCE_OK. Do not use any tools or inspect files.'], env=env, timeout=100)
    events = []
    for line in out.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    complete = (ok and any(e.get('type') == 'text' and 'PROXY_ACCEPTANCE_OK' in e.get('part', {}).get('text', '') for e in events)
                and any(e.get('type') == 'step_finish' for e in events))
    record('stream-completion', complete, 'Complete assistant response: ' + str(complete) + '\n')
    ok, final_status = run('final-state', [str(project / 'proxy'), 'status'])
    final_state = dict(line.split(': ', 1) for line in final_status.splitlines() if ': ' in line)
    record('route-stayed-stable', ok and final_state.get('mode') == 'auto' and final_state.get('pending') == 'none'
           and final_state.get('route') == state.get('route'), final_status)
    failures = [name for name, result in results.items() if not result['passed']]
    (logs / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    print('Logs:', logs, flush=True)
    print('ACCEPTANCE ' + ('FAILED: ' + ', '.join(failures) if failures else 'PASSED'), flush=True)
    raise SystemExit(bool(failures))

def reload_haproxy():
    """Validate configuration, then wait for the master to confirm a graceful reload."""
    import socket
    import subprocess
    import sys

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

if __name__ == '__main__':
    commands = {'verify': verify, '__reload-haproxy': reload_haproxy}
    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        raise SystemExit('Use the proxy command; this module is internal.')
    action = sys.argv.pop(1)
    raise SystemExit(commands[action]())
