"""Offline contract tests for the u-boot-xlnx / arm-trusted-firmware helpers and
the hdl-boot composition. No cross compiler, no network: everything is --dry-run
against fake clones."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UBOOT = ROOT / "targets/u-boot-xlnx/build-uboot.sh"
ATF = ROOT / "targets/arm-trusted-firmware/build-atf.sh"

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, text=True, capture_output=True)


def fake_repo(path, refs):
    """Create a repo with one commit per ref (branches and tags both resolvable)."""
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "t@example.com")
    git(path, "config", "user.name", "t")
    (path / "Makefile").write_text("u-boot.elf:\n\t@echo built\n")
    git(path, "add", "-A")
    git(path, "commit", "-qm", "base")
    for ref in refs:
        git(path, "tag", ref)
    return path


class Workspace(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.ws = Path(self.temporary.name) / "ws"
        (self.ws / "scripts").mkdir(parents=True)
        shutil.copy(UBOOT, self.ws / "scripts/build-uboot.sh")
        shutil.copy(ATF, self.ws / "scripts/build-atf.sh")
        fake_repo(self.ws / "u-boot-xlnx", ["xlnx_rebase_v2025.01_2025.1"])
        fake_repo(self.ws / "arm-trusted-firmware", ["xilinx-v2025.1"])
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("UBOOT_", "ATF_", "HDL_"))}

    def sh(self, script, *args):
        result = subprocess.run(["bash", f"scripts/{script}", *args], cwd=self.ws, text=True,
                                capture_output=True, timeout=60, env=self.env)
        result.stdout = ANSI.sub("", result.stdout)
        result.stderr = ANSI.sub("", result.stderr)
        return result


class UbootTests(Workspace):
    def resolved(self, *args):
        r = self.sh("build-uboot.sh", *args, "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        fields = dict(re.findall(r"^\s+(Board|Ref|Defconfig|DEVICE_TREE|CROSS_COMPILE):\s+(.*)$", r.stdout, re.M))
        return fields, r.stdout

    def test_xilinx_board_follows_release(self):
        f, _ = self.resolved("--board", "zcu102", "--release", "hdl_2023_r2")
        self.assertEqual(f["Ref"], "xlnx_rebase_v2023.01_2023.2")
        self.assertEqual(f["Defconfig"], "xilinx_zynqmp_virt_defconfig")
        self.assertEqual(f["DEVICE_TREE"], "zynqmp-zcu102-rev1.0")
        self.assertEqual(f["CROSS_COMPILE"], "aarch64-linux-gnu-")
        f, _ = self.resolved("--board", "zed", "--release", "hdl_2026_r1")
        self.assertEqual(f["Ref"], "xlnx_rebase_v2025.01_2025.1")
        self.assertEqual(f["Defconfig"], "xilinx_zynq_virt_defconfig")
        self.assertEqual(f["CROSS_COMPILE"], "arm-linux-gnueabihf-")

    def test_adi_boards_pin_their_own_branch_regardless_of_release(self):
        for release in ("hdl_2023_r2", "hdl_2026_r1"):
            f, out = self.resolved("--board", "jupiter_sdr", "--release", release)
            self.assertEqual(f["Ref"], "jupiter-sdr")
            self.assertEqual(f["DEVICE_TREE"], "zynqmp-jupiter-sdr")
            self.assertIn("DEVICE_TREE=zynqmp-jupiter-sdr u-boot.elf", out)
        f, out = self.resolved("--board", "adrv2crr_fmc")
        self.assertEqual((f["Ref"], f["Defconfig"]), ("master", "adi_zynqmp_adrv9009_zu11eg_adrv2crr_fmc_defconfig"))
        self.assertEqual(f["DEVICE_TREE"], "(defconfig default)")
        self.assertNotIn("DEVICE_TREE=", out)
        f, _ = self.resolved("--board", "pluto")
        self.assertEqual((f["Ref"], f["Defconfig"], f["CROSS_COMPILE"]), ("pluto", "zynq_pluto_defconfig", "arm-linux-gnueabihf-"))

    def test_auto_from_hdl_project_and_board(self):
        f, _ = self.resolved("--board", "auto", "--hdl-project", "jupiter_sdr", "--hdl-board", "zcu102")
        self.assertEqual(f["Board"], "jupiter_sdr")   # carrier-less: board ignored
        f, _ = self.resolved("--board", "auto", "--hdl-project", "fmcomms2", "--hdl-board", "zed")
        self.assertEqual(f["Board"], "zed")
        f, _ = self.resolved("--hdl-project", "adrv9009zu11eg", "--hdl-board", "adrv2crr_fmc")
        self.assertEqual(f["Board"], "adrv2crr_fmc")
        r = self.sh("build-uboot.sh", "--board", "auto", "--hdl-project", "fmcomms2", "--hdl-board", "kcu105", "--dry-run")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("No u-boot preset", r.stderr)
        self.assertIn("UBOOT_BOARD", r.stderr)

    def test_explicit_overrides_and_errors(self):
        f, out = self.resolved("--ref", "my-branch", "--defconfig", "xilinx_zynqmp_virt_defconfig",
                               "--device-tree", "zynqmp-foo")
        self.assertEqual((f["Ref"], f["DEVICE_TREE"], f["CROSS_COMPILE"]), ("my-branch", "zynqmp-foo", "aarch64-linux-gnu-"))
        f, _ = self.resolved("--board", "zcu102", "--ref", "pinned-sha")
        self.assertEqual(f["Ref"], "pinned-sha")
        r = self.sh("build-uboot.sh", "--board", "zcu102", "--release", "hdl_1999_r9", "--dry-run")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("No u-boot-xlnx tag known", r.stderr)
        r = self.sh("build-uboot.sh", "--board", "nope", "--dry-run")
        self.assertNotEqual(r.returncode, 0)
        r = self.sh("build-uboot.sh", "--list")
        self.assertEqual(r.returncode, 0, r.stderr)
        for b in ("zed", "zcu102", "jupiter_sdr", "pluto", "m2k", "adrv2crr_fmc", "k26"):
            self.assertRegex(r.stdout, rf"(?m)^{b}\s", msg=b)

    def test_missing_cross_compiler_is_a_clear_error(self):
        bindir = self.ws / "bin"
        bindir.mkdir()
        for tool in ("bash", "git", "grep", "sed", "awk", "head", "nproc", "make", "dirname", "basename", "cat", "tr"):
            real = shutil.which(tool)
            if real:
                (bindir / tool).symlink_to(real)
        r = subprocess.run(["bash", "scripts/build-uboot.sh", "--board", "zcu102"], cwd=self.ws, text=True,
                           capture_output=True, env={"PATH": str(bindir)})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("aarch64-linux-gnu-gcc", ANSI.sub("", r.stderr))

    def test_check_deps_names_missing_packages(self):
        bindir = self.ws / "bin"
        bindir.mkdir()
        for tool in ("bash", "git", "grep", "sed", "awk", "head", "nproc", "make", "dirname", "basename",
                     "cat", "tr", "python3", "bison", "flex", "bc", "dtc"):
            real = shutil.which(tool)
            if real:
                (bindir / tool).symlink_to(real)
        # no cross compiler, no swig, no pkg-config on this PATH
        r = subprocess.run(["bash", "scripts/build-uboot.sh", "--board", "jupiter_sdr", "--check-deps"],
                           cwd=self.ws, text=True, capture_output=True, env={"PATH": str(bindir)})
        self.assertNotEqual(r.returncode, 0)
        err = ANSI.sub("", r.stderr)
        self.assertIn("Missing host build dependencies:", err)
        self.assertIn("aarch64-linux-gnu-gcc", err)
        self.assertIn("swig", err)
        self.assertIn("cim install os-deps --yes", err)
        self.assertIn("gcc-aarch64-linux-gnu", err)
        # the real build path runs the same check before touching git
        r = subprocess.run(["bash", "scripts/build-uboot.sh", "--board", "jupiter_sdr"],
                           cwd=self.ws, text=True, capture_output=True, env={"PATH": str(bindir)})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Missing host build dependencies", ANSI.sub("", r.stderr))

    def test_dirty_checkout_refuses_switch(self):
        (self.ws / "u-boot-xlnx/Makefile").write_text("edited\n")
        # dry-run warns (no compiler needed); the real path stops before fetching
        r = self.sh("build-uboot.sh", "--board", "jupiter_sdr", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dirty", r.stderr)
        git(self.ws / "u-boot-xlnx", "tag", "jupiter-sdr")   # ref already checked out -> no switch, no warning
        r = self.sh("build-uboot.sh", "--board", "jupiter_sdr", "--dry-run")
        self.assertNotIn("dirty", r.stderr)


class AtfTests(Workspace):
    def test_release_to_tag_and_plat(self):
        r = self.sh("build-atf.sh", "--release", "hdl_2023_r2", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Ref:           xilinx-v2023.2", r.stdout)
        self.assertIn("PLAT=zynqmp RESET_TO_BL31=1 CROSS_COMPILE=aarch64-linux-gnu- ZYNQMP_CONSOLE=cadence0", r.stdout)
        self.assertIn("arm-trusted-firmware/bl31.elf", r.stdout)
        r = self.sh("build-atf.sh", "--plat", "versal", "--release", "hdl_2026_r1", "--console", "cadence1", "--dry-run")
        self.assertIn("Ref:           xilinx-v2025.1", r.stdout)
        self.assertIn("PLAT=versal", r.stdout)
        self.assertNotIn("ZYNQMP_CONSOLE", r.stdout)
        r = self.sh("build-atf.sh", "--ref", "xilinx-v2025.2", "--dry-run")
        self.assertIn("Ref:           xilinx-v2025.2", r.stdout)

    def test_bad_inputs(self):
        r = self.sh("build-atf.sh", "--plat", "zynq", "--dry-run")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--plat must be zynqmp or versal", r.stderr)
        r = self.sh("build-atf.sh", "--release", "hdl_1999_r9", "--dry-run")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("No arm-trusted-firmware tag known", r.stderr)


class HdlBootManifestTests(unittest.TestCase):
    def test_hdl_boot_extends_hdl_and_wires_dependencies(self):
        import yaml
        boot = yaml.safe_load((ROOT / "targets/hdl-boot/sdk.yml").read_text())
        hdl = yaml.safe_load((ROOT / "targets/hdl/sdk.yml").read_text())
        self.assertEqual(boot["extends"], "hdl")
        self.assertEqual({g["name"] for g in boot["gits"]}, {"u-boot-xlnx", "arm-trusted-firmware"})
        self.assertEqual(boot["build"]["depends_on"], ["u-boot-xlnx", "arm-trusted-firmware"])
        # the derived build command must stay in sync with the base (whole-value override)
        self.assertEqual(" ".join(boot["build"]["commands"][0].split()), " ".join(hdl["build"][0].split()))
        setv = boot["overlay"]["variables"]["set"]
        self.assertEqual(setv["BUILD_BOOT_BIN"], "true")
        self.assertEqual(setv["BOOT_BIN_UBOOT"], "${{ WORKSPACE }}/u-boot-xlnx/u-boot.elf")
        self.assertEqual(setv["BOOT_BIN_ATF"], "${{ WORKSPACE }}/arm-trusted-firmware/bl31.elf")
        # helper scripts are shared with the standalone targets via symlinks
        # hdl's helpers are re-declared as hdl-boot's own so the workspace gets
        # them with any --source form (cim#89); the overlay drops the inherited ones
        self.assertEqual(sorted(boot["overlay"]["copy_files"]["remove"]), ["hdl.mk", "scripts/build-hdl.sh"])
        self.assertEqual({c["dest"] for c in boot["copy_files"]} & {"scripts/build-hdl.sh", "hdl.mk"},
                         {"scripts/build-hdl.sh", "hdl.mk"})
        for name in ("build-uboot.sh", "build-atf.sh", "build-hdl.sh", "hdl.mk", "os-dependencies.yml"):
            link = ROOT / "targets/hdl-boot" / name
            self.assertTrue(link.is_symlink(), name)
            self.assertTrue(link.resolve().is_file(), name)
        # pins match the standalone targets
        for t, g in (("u-boot-xlnx", "u-boot-xlnx"), ("arm-trusted-firmware", "arm-trusted-firmware")):
            standalone = yaml.safe_load((ROOT / "targets" / t / "sdk.yml").read_text())["gits"][0]
            derived = next(x for x in boot["gits"] if x["name"] == g)
            self.assertEqual((standalone["url"], standalone["commit"]), (derived["url"], derived["commit"]), g)


if __name__ == "__main__":
    unittest.main()
