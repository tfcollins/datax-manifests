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
        # real (empty) clones: a plain directory is not taken for the workspace checkout
        for repo in ("u-boot-xlnx", "arm-trusted-firmware"):
            subprocess.run(["git", "init", "-q", str(self.workspace / repo)], check=True)

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

    def test_uboot_list_json_in_any_argument_order(self):
        for args in (("--list", "--json"), ("--json", "--list"), ("--list", "--board", "zed", "--json"),
                     ("--list", "--dry-run", "--json")):
            res = self.run_uboot(*args)
            self.assertEqual(res.returncode, 0, (args, res.stderr))
            self.assertIn("zcu102", {p["board"] for p in json.loads(res.stdout)})
        self.assertIn("u-boot-xlnx presets", self.run_uboot("--board", "zed", "--list").stdout)

    def test_uboot_json_with_work_actions_is_usage_error(self):
        sentinel = self.workspace / "u-boot-xlnx/u-boot.elf"
        sentinel.write_text("keep")
        for args in (("--clean", "--json"), ("--json", "--clean"),
                     ("--board", "zcu102", "--check-deps", "--json")):
            res = self.run_uboot(*args)
            self.assertEqual(res.returncode, 2, (args, res.stderr))
            self.assertEqual(res.stdout, "")
            self.assertIn("--json cannot be combined", res.stderr)
        self.assertTrue(sentinel.exists())
        # plain config export (no --dry-run) stays allowed and still builds nothing
        res = self.run_uboot("--board", "zcu102", "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(json.loads(res.stdout)["board"], "zcu102")
        # without --json, --clean still cleans
        self.assertEqual(self.run_uboot("--clean").returncode, 0)
        self.assertFalse(sentinel.exists())

    def test_atf_json_with_clean_is_usage_error(self):
        sentinel = self.workspace / "arm-trusted-firmware/bl31.elf"
        sentinel.write_text("keep")
        res = self.run_atf("--clean", "--json")
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertEqual(res.stdout, "")
        self.assertTrue(sentinel.exists())
        self.assertEqual(self.run_atf("--clean").returncode, 0)
        self.assertFalse(sentinel.exists())


if __name__ == "__main__":
    unittest.main()


class ManifestCheckoutSafetyTests(unittest.TestCase):
    """Run from the manifest repo itself, targets/<name>/ is a plain directory next to
    the script: it must never be taken for the workspace clone (git/rm would hit the
    datax-manifests repo). Queries still work; build and clean refuse."""

    def check(self, script, query, *actions):
        res = subprocess.run(["bash", str(script), *query], cwd=ROOT, text=True, capture_output=True, timeout=10)
        self.assertEqual(res.returncode, 0, res.stderr)
        json.loads(res.stdout)
        for action in actions:
            res = subprocess.run(["bash", str(script), *action], cwd=ROOT, text=True, capture_output=True, timeout=10)
            self.assertEqual(res.returncode, 1, (action, res.stdout, res.stderr))
            self.assertIn("Could not locate", res.stderr)

    def test_uboot_from_checkout(self):
        self.check(UBOOT_SCRIPT, ["--board", "zcu102", "--release", "hdl_2026_r1", "--dry-run", "--json"],
                   ["--board", "zcu102", "--release", "hdl_2026_r1"], ["--clean"])

    def test_atf_from_checkout(self):
        self.check(ATF_SCRIPT, ["--plat", "zynqmp", "--release", "hdl_2026_r1", "--dry-run", "--json"],
                   ["--plat", "zynqmp", "--release", "hdl_2026_r1"], ["--plat", "zynqmp", "--clean"])

    def test_real_clone_in_workspace_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "scripts").mkdir()
            shutil.copy(UBOOT_SCRIPT, ws / "scripts/build-uboot.sh")
            subprocess.run(["git", "init", "-q", str(ws / "u-boot-xlnx")], check=True)
            res = subprocess.run(["bash", "scripts/build-uboot.sh", "--board", "zcu102", "--dry-run", "--json"],
                                 cwd=ws, text=True, capture_output=True, timeout=10)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(json.loads(res.stdout)["output"], str(ws.resolve() / "u-boot-xlnx/u-boot.elf"))
