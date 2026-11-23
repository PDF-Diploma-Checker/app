import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common import resource_monitor


class CpuTemperatureTest(unittest.TestCase):
    def _fake_sysfs(self, root, chips):
        for i, (name, temps) in enumerate(chips.items()):
            hwmon = Path(root) / f"hwmon{i}"
            hwmon.mkdir()
            (hwmon / "name").write_text(name + "\n")
            for n, (label, milli) in enumerate(temps, 1):
                (hwmon / f"temp{n}_input").write_text(f"{milli}\n")
                if label:
                    (hwmon / f"temp{n}_label").write_text(label + "\n")

    def _read(self, chips):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            self._fake_sysfs(root, chips)
            real_glob = resource_monitor.glob.glob

            def fake_glob(pattern):
                return real_glob(pattern.replace("/sys/class/hwmon", root).replace("/sys/class/thermal", root + "/no-thermal"))

            with mock.patch.object(resource_monitor.sys, "platform", "linux"), \
                    mock.patch.object(resource_monitor.glob, "glob", fake_glob):
                return resource_monitor.cpu_temperature()

    def test_package_sensor_wins_over_a_cooler_core(self):
        value = self._read({"nvme": [("Composite", 70000)],
                            "coretemp": [("Core 0", 50000), ("Package id 0", 61000)]})
        self.assertEqual(value, 61.0)

    def test_amd_tctl(self):
        self.assertEqual(self._read({"k10temp": [("Tctl", 72500)]}), 72.5)

    def test_no_cpu_sensor_gives_none(self):
        self.assertIsNone(self._read({"nvme": [("Composite", 40000)]}))

    def test_windows_has_no_reading(self):
        with mock.patch.object(resource_monitor.sys, "platform", "win32"):
            self.assertIsNone(resource_monitor.cpu_temperature())


if __name__ == "__main__":
    unittest.main()
