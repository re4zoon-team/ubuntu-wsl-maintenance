"""Runtime refresh tests with isolated homes and mocked service commands."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1] / 'packages/proxy-runtime'
spec = importlib.util.spec_from_file_location('refresh', PACKAGE / 'refresh.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.load_settings = lambda path: path.read_text()


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        with patch.object(Path, 'home', return_value=self.home):
            self.runtime = module.Runtime(PACKAGE)
        self.runtime.fake_system = True
        shutil.copytree(PACKAGE, self.runtime.root)
        (self.runtime.root / 'old-marker').write_text('previous runtime')
        (self.runtime.root / 'config/proxy.yaml').write_text('upstream_host: custom.example\nupstream_port: 8080\n')
        self.runtime.manifest_path.parent.mkdir(parents=True)
        self.runtime.manifest_path.write_text(json.dumps(dict(status='installed', home=str(self.home), root=str(self.runtime.root))))
        self.runtime.run = lambda *args, **kwargs: None
        self.runtime.ctl = lambda *args, **kwargs: None

    def test_runtime_only_refresh_preserves_configuration(self):
        self.runtime.refresh()
        self.assertFalse((self.runtime.root / 'old-marker').exists())
        self.assertIn('custom.example', (self.runtime.root / 'config/proxy.yaml').read_text())
        self.assertFalse((self.runtime.root / 'installer.py').exists())

    def test_failed_restart_restores_previous_runtime(self):
        def ctl(*args, **kwargs):
            if args[0] == 'restart' and kwargs.get('check', True):
                raise subprocess.CalledProcessError(1, 'systemctl')
        self.runtime.ctl = ctl
        with self.assertRaises(subprocess.CalledProcessError):
            self.runtime.refresh()
        self.assertTrue((self.runtime.root / 'old-marker').exists())

    def test_missing_installation_defers(self):
        self.runtime.manifest_path.unlink()
        self.runtime.refresh()
        self.assertTrue((self.runtime.root / 'old-marker').exists())


if __name__ == '__main__':
    unittest.main()
