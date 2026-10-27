"""Tests for u-boot-xlnx and arm-trusted-firmware helper scripts."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
UBOOT_SCRIPT = ROOT / "targets/u-boot-xlnx/build-uboot.sh"
ATF_SCRIPT = ROOT / "targets/arm-trusted-firmware/build-atf.sh"


class FirmwareScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        (self.workspace / "scripts").mkdir()
        shutil.copy(UBOOT_SCRIPT, self.workspace / "scripts/build-uboot.sh")
        shutil.copy(ATF_SCRIPT, self.workspace / "scripts/build-atf.sh")
        (self.workspace / "u-boot-xlnx").mkdir()
        (self.workspace / "arm-trusted-firmware").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_uboot(self, *args):
        return subprocess.run(["bash", str(self.workspace / "scripts/build-uboot.sh"), *args],
                              cwd=self.workspace, text=True, capture_output=True, timeout=10)

    def run_atf(self, *args):
        return subprocess.run(["bash", str(self.workspace / "scripts/build-atf.sh"), *args],
                              cwd=self.workspace, text=True, capture_output=True, timeout=10)

    def test_uboot_list_json(self):
        res = self.run_uboot("--list", "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        presets = json.loads(res.stdout)
        self.assertIsInstance(presets, list)
        boards = {p["board"] for p in presets}
        self.assertIn("zcu102", boards)
        self.assertIn("zed", boards)
        self.assertIn("jupiter_sdr", boards)

    def test_uboot_dry_run_json(self):
        res = self.run_uboot("--board", "zcu102", "--release", "hdl_2026_r1", "--dry-run", "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        data = json.loads(res.stdout)
        self.assertEqual(data["target"], "u-boot-xlnx")
        self.assertEqual(data["board"], "zcu102")
        self.assertEqual(data["ref"], "xlnx_rebase_v2025.01_2025.1")
        self.assertEqual(data["defconfig"], "xilinx_zynqmp_virt_defconfig")
        self.assertEqual(data["device_tree"], "zynqmp-zcu102-rev1.0")
        self.assertEqual(data["cross_compile"], "aarch64-linux-gnu-")
        self.assertIn("u-boot.elf", data["output"])
        self.assertIn("make", data["commands"]["build"])

    def test_uboot_jupiter_sdr_json(self):
        res = self.run_uboot("--board", "jupiter_sdr", "--dry-run", "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        data = json.loads(res.stdout)
        self.assertEqual(data["ref"], "jupiter-sdr")
        self.assertEqual(data["device_tree"], "zynqmp-jupiter-sdr")

    def test_atf_dry_run_json(self):
        res = self.run_atf("--plat", "zynqmp", "--release", "hdl_2026_r1", "--dry-run", "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        data = json.loads(res.stdout)
        self.assertEqual(data["target"], "arm-trusted-firmware")
        self.assertEqual(data["plat"], "zynqmp")
        self.assertEqual(data["ref"], "xilinx-v2025.1")
        self.assertEqual(data["console"], "cadence0")
        self.assertEqual(data["cross_compile"], "aarch64-linux-gnu-")
        self.assertIn("bl31.elf", data["output"])
        self.assertIn("make", data["commands"]["build"])

    def test_atf_versal_json(self):
        res = self.run_atf("--plat", "versal", "--release", "hdl_2023_r2", "--dry-run", "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        data = json.loads(res.stdout)
        self.assertEqual(data["plat"], "versal")
        self.assertEqual(data["ref"], "xilinx-v2023.2")
        self.assertIsNone(data["console"])


if __name__ == "__main__":
    unittest.main()
