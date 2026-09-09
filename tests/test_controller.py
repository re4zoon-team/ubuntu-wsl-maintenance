"""Controller behavior with temporary state and mocked sockets/services."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1] / 'packages/proxy-runtime'
sys.path.insert(0, str(PACKAGE / 'lib'))
from controller import Controller, read_state


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        with patch.object(Path, 'home', return_value=Path(self.temporary.name)):
            self.controller = Controller(PACKAGE)

    def test_monitor_debounces_and_manual_mode_is_persistent(self):
        with patch('controller.socket.create_connection'), patch.object(self.controller, 'reload'):
            self.controller.change('check')
            self.assertEqual(read_state(self.controller.state_path)['PROXY_EFFECTIVE'], 'off')
            self.controller.change('check')
            self.assertEqual(read_state(self.controller.state_path)['PROXY_EFFECTIVE'], 'on')
            self.controller.change('off')
            self.controller.change('check')
            state = read_state(self.controller.state_path)
            self.assertEqual(state['PROXY_MODE'], 'force-off')
            self.assertEqual(state['PROXY_EFFECTIVE'], 'off')
            self.controller.change('auto')
            self.controller.change('check')
        with patch('controller.socket.create_connection', side_effect=OSError), patch.object(self.controller, 'reload'):
            self.controller.change('check')
            self.controller.change('check')
            self.assertEqual(read_state(self.controller.state_path)['PROXY_EFFECTIVE'], 'on')
            self.controller.change('check')
            self.assertEqual(read_state(self.controller.state_path)['PROXY_EFFECTIVE'], 'off')

    def test_failed_reload_preserves_state_and_retries_pending_transition(self):
        self.controller.change('render-config')
        with patch.object(self.controller, 'reload', side_effect=[RuntimeError('reload failed'), None]):
            with self.assertRaises(RuntimeError):
                self.controller.change('on')
        self.assertEqual(read_state(self.controller.state_path)['PROXY_EFFECTIVE'], 'off')
        self.assertIn('server direct', self.controller.config_path.read_text())
        self.assertTrue(self.controller.pending_path.exists())
        with patch.object(self.controller, 'reload'), patch('controller.socket.create_connection') as probe:
            self.controller.change('check')
            probe.assert_not_called()
        self.assertEqual(read_state(self.controller.state_path)['PROXY_EFFECTIVE'], 'on')
        self.assertFalse(self.controller.pending_path.exists())

    def test_state_is_parsed_as_data_not_shell(self):
        path = self.controller.state_path
        path.parent.mkdir(parents=True)
        path.write_text('PROXY_MODE=$(touch should-not-exist)\n')
        with self.assertRaises(ValueError):
            read_state(path)


if __name__ == '__main__':
    unittest.main()
