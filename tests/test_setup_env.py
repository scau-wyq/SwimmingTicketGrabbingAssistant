"""安装流程测试：模拟 pip，不下载依赖或修改真实环境。"""
import importlib.util
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('setup_env', Path(__file__).resolve().parents[1] / 'scripts/setup-env.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SetupTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'config.example.toml').write_text('[capture]\nmitmdump = ""\n', encoding='utf-8')
        environment = self.root / '.venv'
        (environment / 'Scripts').mkdir(parents=True)
        (environment / 'Scripts/python.exe').touch()
        (environment / 'pyvenv.cfg').touch()
        root_patch = patch.object(setup, 'ROOT', self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        version = patch.object(setup.sys, 'version_info', (3, 12))
        version.start()
        self.addCleanup(version.stop)

    def test_existing_config_preserved_and_doctor_failure_reported(self):
        config = self.root / 'config.toml'
        config.write_bytes(b'local configuration')
        with patch.object(setup, 'run'), patch.object(setup.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)):
            self.assertEqual(setup.install(), 2)
        self.assertEqual(config.read_bytes(), b'local configuration')

    def test_missing_config_created_after_dependencies_succeed(self):
        with patch.object(setup, 'run'), patch.object(setup.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
            self.assertEqual(setup.install(), 0)
        self.assertEqual((self.root / 'config.toml').read_bytes(), (self.root / 'config.example.toml').read_bytes())

    def test_pip_failure_stops_before_configuration_or_doctor(self):
        with patch.object(setup, 'run', side_effect=[None, subprocess.CalledProcessError(1, 'pip')]), \
                patch.object(setup.subprocess, 'run') as doctor:
            with self.assertRaises(subprocess.CalledProcessError):
                setup.install()
            doctor.assert_not_called()
        self.assertFalse((self.root / 'config.toml').exists())
