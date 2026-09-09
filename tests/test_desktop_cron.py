import base64
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml


def load(name):
    path = Path(__file__).resolve().parents[1] / 'scripts' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DesktopCronTests(unittest.TestCase):
    def test_shortcut_uses_custom_icon_and_actual_distro(self):
        module = load('desktop-shortcut')
        with patch.object(module.os, 'geteuid', return_value=1000), \
             patch.object(module.Path, 'is_file', return_value=True), \
             patch.object(module.subprocess, 'check_output', side_effect=[
                 '\\\\wsl.localhost\\Company-Dev-E2E\\\n', '\\\\wsl.localhost\\Company-Dev-E2E\\home\\dev\\maintenance.ico\n']), \
             patch.object(module.subprocess, 'run') as run:
            module.main()
        args = run.call_args.args[0]
        script = base64.b64decode(args[-1]).decode('utf-16le')
        self.assertIn('-d Company-Dev-E2E --cd ~ --exec /usr/bin/xclock', script)
        self.assertIn('company-maintenance.ico', script)
        self.assertIn('$shortcut.IconLocation = "$icon,0"', script)
        self.assertEqual(run.call_args.kwargs['env']['WSL_INTEROP'], '/run/WSL/1_interop')

    def test_cron_only_replaces_its_user_marker(self):
        module = load('placeholder-cron')
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(module.Path, 'home', return_value=Path(temporary)), \
             patch.object(module.os, 'geteuid', return_value=1000):
            module.main()
            module.main()
            files = list(Path(temporary).rglob('*.yaml'))
            self.assertEqual(len(files), 1)
            record = yaml.safe_load(files[0].read_text())
            self.assertEqual(record['uid'], 1000)
            self.assertEqual(record['task'], 'placeholder-cron')
            self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)

    def test_both_tasks_reject_root(self):
        for name in ('desktop-shortcut', 'placeholder-cron'):
            module = load(name)
            with patch.object(module.os, 'geteuid', return_value=0), self.assertRaises(SystemExit):
                module.main()


if __name__ == '__main__':
    unittest.main()
