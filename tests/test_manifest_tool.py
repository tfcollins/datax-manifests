"""Tests for scripts/manifest-tool.py."""

import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/manifest-tool.py"


class ManifestToolTests(unittest.TestCase):
    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args],
                              cwd=ROOT, text=True, capture_output=True, timeout=10)

    def test_list_targets_json(self):
        res = self.run_tool("--list-targets", "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        targets = json.loads(res.stdout)
        self.assertIsInstance(targets, list)
        names = {t["name"] for t in targets}
        for expected in ("adi-linux", "arm-trusted-firmware", "hdl", "hdl-boot", "u-boot-xlnx"):
            self.assertIn(expected, names)

        # Check hdl-boot extends hdl
        hdl_boot = next(t for t in targets if t["name"] == "hdl-boot")
        self.assertEqual(hdl_boot["extends"], "hdl")

    def test_target_inspection_json(self):
        res = self.run_tool("--target", "hdl", "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        info = json.loads(res.stdout)
        self.assertEqual(info["name"], "hdl")
        self.assertIn("HDL_RELEASE", info["variables"])
        self.assertEqual(info["variables"]["HDL_RELEASE"]["default"], "hdl_2026_r1")
        self.assertTrue(len(info["variables"]["HDL_RELEASE"]["description"]) > 0)
        self.assertIn("common_deps", info["os_dependencies"])
        self.assertTrue(any(g["name"] == "hdl" for g in info["gits"]))

    def test_target_extends_resolution(self):
        res = self.run_tool("--target", "hdl-boot", "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        info = json.loads(res.stdout)
        self.assertEqual(info["name"], "hdl-boot")
        self.assertEqual(info["extends"], "hdl")
        # Overlaid variables
        self.assertEqual(info["variables"]["BUILD_BOOT_BIN"]["default"], "true")
        self.assertIn("u-boot-xlnx", info["variables"]["BOOT_BIN_UBOOT"]["default"])
        # Inherited variables
        self.assertIn("HDL_RELEASE", info["variables"])
        # Added variables
        self.assertIn("UBOOT_BOARD", info["variables"])
        # Merged gits
        git_names = {g["name"] for g in info["gits"]}
        self.assertIn("hdl", git_names)
        self.assertIn("u-boot-xlnx", git_names)
        self.assertIn("arm-trusted-firmware", git_names)

    def test_all_targets_json(self):
        res = self.run_tool("--all", "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        data = json.loads(res.stdout)
        self.assertIsInstance(data, dict)
        self.assertEqual(len(data), 5)
        self.assertIn("adi-linux", data)
        self.assertIn("hdl", data)

    def test_extends_inherits_makefile_include_and_copy_files(self):
        info = json.loads(self.run_tool("--target", "hdl-boot", "--json").stdout)
        self.assertEqual(info["makefile_include"], ["include hdl.mk", "include boot.mk"])
        dests = [c["dest"] for c in info["copy_files"]]
        self.assertEqual(len(dests), len(set(dests)), dests)
        for dest in ("scripts/build_boot_bin.sh", "scripts/build_zynqmp_boot_bin.sh",
                     "scripts/build_versal_boot_bin.sh"):
            entry = next(c for c in info["copy_files"] if c["dest"] == dest)
            self.assertTrue(entry["source"].startswith("https://raw.githubusercontent.com/analogdevicesinc/wiki-scripts/"))
        # overlay.copy_files.remove drops the parent's entry; the child re-declares it once
        for dest in ("scripts/build-hdl.sh", "scripts/hdl-prebuilt.py", "hdl.mk", "boot.mk",
                     "scripts/build-uboot.sh", "scripts/build-atf.sh"):
            self.assertEqual(dests.count(dest), 1, dest)
        # the base target is unchanged
        hdl = json.loads(self.run_tool("--target", "hdl", "--json").stdout)
        self.assertEqual(hdl["makefile_include"], ["include hdl.mk"])

    def test_missing_pyyaml_is_a_clear_error(self):
        code = ("import runpy, sys; sys.modules['yaml'] = None; "
                f"sys.argv = ['manifest-tool.py', '-t', 'hdl', '--json']; "
                f"runpy.run_path({str(SCRIPT)!r}, run_name='__main__')")
        res = subprocess.run([sys.executable, "-c", code], cwd=ROOT, text=True, capture_output=True, timeout=10)
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertEqual(res.stdout, "")
        self.assertIn("pip install pyyaml", res.stderr)
        self.assertIn("apt install python3-yaml", res.stderr)


if __name__ == "__main__":
    unittest.main()
