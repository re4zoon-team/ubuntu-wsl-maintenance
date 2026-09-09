"""Task privilege and no-op checks; never invoke Docker cleanup."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/docker-cleaner.py'
spec = importlib.util.spec_from_file_location('cleaner', SCRIPT)
cleaner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleaner)


class TaskTests(unittest.TestCase):
    def test_proxy_task_passes_its_own_package_version(self):
        spec = importlib.util.spec_from_file_location('proxy_task', SCRIPT.with_name('proxy-refresh.py'))
        task = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(task)
        with patch.object(task.os, 'geteuid', return_value=1000), patch.object(task.subprocess, 'run') as run:
            task.main()
            self.assertEqual(run.call_args.args[0][-2:], ['--version', '1.0.0'])

    def test_non_root_is_rejected(self):
        with patch.object(cleaner.os, 'geteuid', return_value=1000), patch.object(cleaner.subprocess, 'run') as run:
            with self.assertRaises(RuntimeError):
                cleaner.main()
            run.assert_not_called()

    def test_inactive_docker_is_a_noop(self):
        with patch.object(cleaner.os, 'geteuid', return_value=0), patch.object(cleaner.subprocess, 'run', return_value=SimpleNamespace(returncode=3)) as run:
            cleaner.main()
            run.assert_called_once_with(['systemctl', 'is-active', '--quiet', 'docker.service'])

    def test_cleanup_keeps_seven_day_filter_and_does_not_prune_volumes(self):
        with patch.object(cleaner.os, 'geteuid', return_value=0), patch.object(cleaner.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            cleaner.main()
            self.assertEqual(run.call_args.args[0], ['docker', 'system', 'prune', '--force', '--filter', 'until=168h'])


if __name__ == '__main__':
    unittest.main()
