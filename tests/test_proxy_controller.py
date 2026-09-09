"""Local controller checks: no services, sudo, or network access."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PROXY = Path(__file__).resolve().parents[1] / 'packages/proxy-runtime/proxy'


class ControllerTests(unittest.TestCase):
    def test_current_state_roundtrip_supports_bash_and_zsh(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            state = home / '.cache/.proxy-state'
            state.parent.mkdir()
            state.write_text(
                'PROXY_MODE=force-off\nPROXY_DETECTED=off\nPROXY_EFFECTIVE=off\n'
                'PROXY_SUCCESS_COUNT=0\nPROXY_FAILURE_COUNT=3\n'
                'export HTTP_PROXY=http://127.0.0.1:18080\n'
                'export HTTPS_PROXY=http://127.0.0.1:18080\n'
                'export http_proxy=http://127.0.0.1:18080\n'
                'export https_proxy=http://127.0.0.1:18080\n'
                'export NO_PROXY=localhost,127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.nav.gov.hu\n'
                'export no_proxy=localhost,127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.nav.gov.hu\n'
            )
            env = {key: value for key, value in os.environ.items() if not key.startswith('PROXY_')}
            env['HOME'] = directory
            for action in ['render-config', 'auto']:
                result = subprocess.run(['/usr/bin/python3', str(PROXY), action], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            text = state.read_text()
            self.assertIn('PROXY_MODE=auto', text)
            self.assertNotIn('CA_BUNDLE', text)
            self.assertNotIn('SSL_CERT_FILE', text)
            for shell in ['bash', 'zsh']:
                subprocess.run([shell, '-c', '. "$1"; test "$HTTP_PROXY" = http://127.0.0.1:18080',
                                'test', str(state)], env=env, check=True, capture_output=True)

    def test_removed_commands_are_not_exposed(self):
        help_text = subprocess.check_output(['/usr/bin/python3', str(PROXY), 'help'], text=True)
        self.assertNotIn('verify', help_text)
        self.assertNotIn('test ', help_text)
        for command in ['init', 'kill']:
            result = subprocess.run(['/usr/bin/python3', str(PROXY), command], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Unknown proxy command', result.stderr)


if __name__ == '__main__':
    unittest.main()
