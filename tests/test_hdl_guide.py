"""Offline contract tests for targets/hdl/build-hdl.sh release handling."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "targets/hdl/build-hdl.sh"

# Project/board stubs per fake release; the Makefile include decides the tool.
# A project whose value is a plain tool string has no carrier boards (SOM-style
# designs such as jupiter_sdr/pluto): its Makefile sits in the project dir.
RELEASES = {
    "hdl_2023_r2": {"fmcomms2": {"zed": "xilinx", "zcu102": "xilinx"},
                    "ad9361": {"a10soc": "intel"},
                    "pluto": "xilinx"},
    "hdl_2026_r1": {"fmcomms2": {"zcu102": "xilinx", "kcu105": "xilinx"},
                    "ad9081_fmca_ebz": {"vck190": "xilinx"},
                    "cn0561": {"de10nano": "intel"},
                    "jupiter_sdr": "xilinx"},
}


def write_project_makefile(path, name, tool):
    path.mkdir(parents=True)
    depth = "../" * (len(path.relative_to(path.parents[len(path.parts) - 1 - path.parts.index("projects") - 1]).parts) - 1)
    (path / "Makefile").write_text(
        f"PROJECT_NAME := {name}\ninclude {depth}scripts/project-{tool}.mk\n")


def git(cwd, *args, **kwargs):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, text=True,
                          capture_output=True, **kwargs)


def make_upstream(path):
    """Create a fake analogdevicesinc/hdl with one branch per release."""
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "test")
    for release, projects in RELEASES.items():
        git(path, "checkout", "-q", "--orphan", release)
        git(path, "rm", "-rfq", "--ignore-unmatch", ".")
        for stale in path.glob("projects"):
            shutil.rmtree(stale)
        for project, boards in projects.items():
            if isinstance(boards, str):
                write_project_makefile(path / "projects" / project, project, boards)
                continue
            for board, tool in boards.items():
                write_project_makefile(path / "projects" / project / board,
                                       f"{project}_{board}", tool)
        # Device info the way the real repo carries it: carrier-less projects name
        # their part in system_project.tcl, carrier boards come from a lookup table.
        for project, boards in projects.items():
            if isinstance(boards, str):
                part = "xczu3eg-sfva625-2-e" if project == "jupiter_sdr" else "xc7z010clg225-1"
                (path / "projects" / project / "system_project.tcl").write_text(
                    f'adi_project_create {project} 0 {{}} "{part}"\n')
        (path / "projects/scripts").mkdir(exist_ok=True)
        (path / "projects/scripts/adi_project_xilinx.tcl").write_text(
            'if [regexp "_zed" $project_name] {\n  set device "xc7z020clg484-1"\n}\n'
            'if [regexp "_zcu102" $project_name] {\n  set device "xczu9eg-ffvb1156-2-e"\n}\n'
            'if [regexp "_vck190" $project_name] {\n  set device "xcvc1902-vsva2197-2MP-e-S"\n}\n'
            'if [regexp "_kcu105" $project_name] {\n  set device "xcku040-ffva1156-2-e"\n}\n')
        (path / "RELEASE").write_text(release + "\n")
        git(path, "add", "-A")
        git(path, "commit", "-qm", release)
    git(path, "checkout", "-q", "hdl_2026_r1")


class HdlGuideTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.upstream = root / "upstream"
        make_upstream(self.upstream)
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        # Mirror what cim init produces: hdl/ clone at the default release plus scripts/
        subprocess.run(["git", "clone", "-q", "-b", "hdl_2026_r1", str(self.upstream),
                        str(self.workspace / "hdl")], check=True, capture_output=True)
        git(self.workspace / "hdl", "config", "user.email", "test@example.com")
        git(self.workspace / "hdl", "config", "user.name", "test")
        (self.workspace / "scripts").mkdir()
        shutil.copy(SCRIPT, self.workspace / "scripts" / "build-hdl.sh")
        for helper in ("build_boot_bin.sh", "build_zynqmp_boot_bin.sh", "build_versal_boot_bin.sh"):
            (self.workspace / "scripts" / helper).write_text("#!/bin/bash\necho STUB $0 $@\n")
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("HDL_RELEASE", "VIVADO", "XILINX_VIVADO")}

    def run_script(self, *args, env=None, input=""):
        return subprocess.run(["bash", "scripts/build-hdl.sh", *args], cwd=self.workspace,
                              text=True, capture_output=True, timeout=60, input=input,
                              env={**self.env, **(env or {})})

    def head_branch(self):
        return git(self.workspace / "hdl", "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def projects_listed(self, stdout):
        return {line.split("|")[0].strip() for line in stdout.splitlines()
                if "|" in line and not line.startswith("PROJECT")}

    def test_default_release_lists_without_switching(self):
        result = self.run_script("--list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Switching hdl/", result.stderr)
        self.assertEqual(self.projects_listed(result.stdout), set(RELEASES["hdl_2026_r1"]))
        self.assertEqual(self.head_branch(), "hdl_2026_r1")

    def test_release_flag_switches_checkout_and_matrix(self):
        result = self.run_script("--release", "hdl_2023_r2", "--list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Switching hdl/ to release 'hdl_2023_r2'", result.stderr)
        self.assertEqual(self.projects_listed(result.stdout), set(RELEASES["hdl_2023_r2"]))
        self.assertEqual(self.head_branch(), "hdl_2023_r2")
        # Flag order must not matter and switching back must work
        result = self.run_script("--list", "--release", "hdl_2026_r1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.projects_listed(result.stdout), set(RELEASES["hdl_2026_r1"]))
        self.assertEqual(self.head_branch(), "hdl_2026_r1")

    def test_release_env_var_is_honoured(self):
        result = self.run_script("--list-projects", env={"HDL_RELEASE": "hdl_2023_r2"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("(hdl_2023_r2)", result.stdout)
        self.assertEqual(self.head_branch(), "hdl_2023_r2")

    def test_release_by_commit_sha(self):
        sha = git(self.upstream, "rev-parse", "hdl_2023_r2").stdout.strip()
        result = self.run_script("--release", sha, "--list-projects")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(git(self.workspace / "hdl", "rev-parse", "HEAD").stdout.strip(), sha)

    def test_unknown_release_fails_clearly(self):
        result = self.run_script("--release", "hdl_1999_r9", "--list")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hdl_1999_r9", result.stderr)
        self.assertEqual(self.head_branch(), "hdl_2026_r1")

    def test_dirty_worktree_refuses_switch(self):
        (self.workspace / "hdl" / "RELEASE").write_text("edited\n")
        result = self.run_script("--release", "hdl_2023_r2", "--list")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("dirty", result.stderr)
        self.assertEqual(self.head_branch(), "hdl_2026_r1")
        # Untracked build output must not count as dirty
        (self.workspace / "hdl" / "RELEASE").write_text("hdl_2026_r1\n")
        (self.workspace / "hdl" / "projects" / "fmcomms2" / "zcu102" / "build").mkdir()
        result = self.run_script("--release", "hdl_2023_r2", "--list")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_check_tools_resolves_vivado_from_release(self):
        result = self.run_script("--check-tools", "--release", "hdl_2023_r2", "--vivado", "auto")
        self.assertIn("Vivado version:  2023.2", result.stdout)
        result = self.run_script("--check-tools", "--release", "hdl_2026_r1")
        self.assertIn("Vivado version:  2025.1", result.stdout)
        result = self.run_script("--check-tools", "--vivado", "/x/y/2042.9/Vivado")
        self.assertIn("(/x/y/2042.9/Vivado)", result.stdout)

    def test_unknown_release_without_vivado_names_the_override(self):
        git(self.upstream, "branch", "hdl_experimental", "hdl_2026_r1")
        result = self.run_script("--check-tools", "--release", "hdl_experimental")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("set VIVADO=", result.stdout)
        result = self.run_script("--project", "fmcomms2", "--board", "zcu102", "--dry-run",
                                 "--release", "hdl_experimental")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("VIVADO=", result.stderr)
        # An explicit Vivado path makes the same release buildable
        result = self.run_script("--project", "fmcomms2", "--board", "zcu102", "--dry-run",
                                 "--release", "hdl_experimental", "--vivado", "/opt/Xilinx/2025.1/Vivado")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("/opt/Xilinx/2025.1/Vivado/settings64.sh", result.stdout)

    def test_dry_run_uses_release_matrix(self):
        # zed only exists in hdl_2023_r2
        result = self.run_script("--project", "fmcomms2", "--board", "zed", "--dry-run")
        self.assertNotEqual(result.returncode, 0)
        result = self.run_script("--project", "fmcomms2", "--board", "zed", "--dry-run",
                                 "--release", "hdl_2023_r2", "--boot-bin", "true")
        self.assertEqual(result.returncode, 0, result.stderr)
        # Auto-resolution probes several install prefixes, so only the version is
        # host-independent: /opt/Xilinx/2023.2/Vivado or /opt/Xilinx/Vivado/2023.2 ...
        self.assertRegex(result.stdout, r'source "/(opt|tools)/Xilinx/(2023\.2/Vivado|Vivado/2023\.2)/settings64\.sh"')
        self.assertNotIn("2025.1", result.stdout)
        self.assertIn("scripts/build_boot_bin.sh", result.stdout)   # zed is Zynq-7000
        self.assertFalse((self.workspace / "hdl/projects/fmcomms2/zed/build").exists())

    def test_carrierless_project_listed_and_described(self):
        result = self.run_script("--list")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [line for line in result.stdout.splitlines() if line.startswith("jupiter_sdr")]
        self.assertEqual(len(rows), 1)
        self.assertEqual([c.strip() for c in rows[0].split("|")][:2], ["jupiter_sdr", "-"])
        self.assertIn("Vivado", rows[0])
        result = self.run_script("--list-boards", "jupiter_sdr")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no carrier boards", result.stdout)
        self.assertIn("HDL_PROJECT=jupiter_sdr", result.stdout)
        # --project alone is enough; no HINT to add --board
        result = self.run_script("--project", "jupiter_sdr", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("[HINT]", result.stdout)

    def test_carrierless_project_builds_in_project_dir_ignoring_board(self):
        # sdk.yml always passes the default HDL_BOARD; it must be ignored with a warning
        result = self.run_script("--project", "jupiter_sdr", "--board", "zcu102", "--dry-run",
                                 "--boot-bin", "true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ignoring HDL_BOARD=zcu102", result.stdout)
        self.assertIn('-C "' + str(self.workspace / "hdl/projects/jupiter_sdr") + '"', result.stdout)
        self.assertNotIn("projects/jupiter_sdr/zcu102", result.stdout)
        # BOOT.BIN path uses the Makefile's PROJECT_NAME, not <proj>_<board>
        self.assertIn("build/jupiter_sdr.sdk/system_top.xsa", result.stdout)
        # Carrier projects still use PROJECT_NAME from their Makefile too
        result = self.run_script("--project", "fmcomms2", "--board", "zcu102", "--dry-run",
                                 "--boot-bin", "true")
        self.assertIn("build/fmcomms2_zcu102.sdk/system_top.xsa", result.stdout)
        # Not carrier-less on a release where it does not exist
        result = self.run_script("--project", "pluto", "--dry-run")
        self.assertNotEqual(result.returncode, 0)
        result = self.run_script("--project", "pluto", "--dry-run", "--release", "hdl_2023_r2")
        self.assertEqual(result.returncode, 0, result.stderr)

    def wizard(self, answers):
        result = self.run_script("--interactive", input="".join(a + "\n" for a in answers))
        # the summary is colourised; compare plain text
        result.stdout = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
        return result

    def test_wizard_offers_boot_bin_for_zynq_designs_only(self):
        # release, project, [board], jobs, dir, [boot], confirm=no
        result = self.wizard(["", "jupiter_sdr", "", "", "y", "n"])
        self.assertEqual(result.returncode, 0, result.stderr)
        # (read -p prompts are not emitted on a non-tty stdin, so assert on outcomes)
        self.assertIn("Generate BOOT.BIN:     true (zynqmp)", result.stdout)
        self.assertIn("HDL_PROJECT=jupiter_sdr DIR_NAME=build", result.stdout)
        self.assertIn("BUILD_BOOT_BIN=true sdk-build", result.stdout)
        # Carrier design on a Zynq board via the lookup table
        result = self.wizard(["", "fmcomms2", "zcu102", "", "", "y", "n"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Generate BOOT.BIN:     true", result.stdout)
        # Versal boots from a BOOT.BIN too
        result = self.wizard(["", "ad9081_fmca_ebz", "vck190", "", "", "y", "n"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Generate BOOT.BIN:     true (versal)", result.stdout)
        # Kintex has no boot ROM: no prompt, flag stays false, confirm consumes "n"
        result = self.wizard(["", "fmcomms2", "kcu105", "", "", "n"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not applicable", result.stdout)
        self.assertIn("Generate BOOT.BIN:     false", result.stdout)
        # Intel: no prompt either
        result = self.wizard(["", "cn0561", "de10nano", "", "", "n"])
        self.assertIn("not applicable", result.stdout)
        self.assertIn("Generate BOOT.BIN:     false", result.stdout)

    def boot_bin_line(self, *args):
        result = self.run_script(*args, "--dry-run", "--boot-bin", "true", "--boot-bin-uboot",
                                 "/u/u-boot.elf", "--boot-bin-atf", "/a/bl31.elf")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = [l for l in result.stdout.splitlines() if l.startswith("3) ")]
        return result.stdout, (lines[0] if lines else "")

    def test_boot_bin_helper_matches_boot_architecture(self):
        # Zynq-7000 -> build_boot_bin.sh (xsa, u-boot)
        out, line = self.boot_bin_line("--project", "pluto", "--release", "hdl_2023_r2")
        self.assertIn('scripts/build_boot_bin.sh" "build/pluto.sdk/system_top.xsa" "/u/u-boot.elf"', line)
        self.assertNotIn("bl31", line)
        self.assertIn("BOOT.BIN:          zynq", out)
        # ZynqMP (carrier-less, part from system_project.tcl) -> build_zynqmp_boot_bin.sh (xsa, u-boot, atf)
        out, line = self.boot_bin_line("--project", "jupiter_sdr")
        self.assertIn('scripts/build_zynqmp_boot_bin.sh" "build/jupiter_sdr.sdk/system_top.xsa" "/u/u-boot.elf" "/a/bl31.elf"', line)
        self.assertIn("BOOT.BIN:          zynqmp", out)
        # ZynqMP carrier design via the board table
        out, line = self.boot_bin_line("--project", "fmcomms2", "--board", "zcu102")
        self.assertIn('build_zynqmp_boot_bin.sh" "build/fmcomms2_zcu102.sdk/system_top.xsa"', line)
        # Versal -> build_versal_boot_bin.sh
        out, line = self.boot_bin_line("--project", "ad9081_fmca_ebz", "--board", "vck190")
        self.assertIn("build_versal_boot_bin.sh", line)
        self.assertIn("BOOT.BIN:          versal", out)
        # Kintex has no boot ROM: BOOT.BIN silently skipped with a warning naming the device
        out, line = self.boot_bin_line("--project", "fmcomms2", "--board", "kcu105")
        self.assertEqual(line, "")
        self.assertIn("does not target a Zynq / ZynqMP / Versal device (device: xcku040", out)
        # Intel
        out, line = self.boot_bin_line("--project", "cn0561", "--board", "de10nano")
        self.assertEqual(line, "")

    def test_boot_bin_atf_download_warns_without_cross_compiler(self):
        # Hide the cross-compiler by shadowing PATH with an empty dir plus a stub git/make
        bindir = self.workspace / "bin"
        bindir.mkdir()
        for tool in ("bash", "git", "grep", "sed", "awk", "head", "tr", "basename", "dirname", "find", "sort", "nproc", "column", "cat", "printf", "unzip"):
            real = shutil.which(tool)
            if real:
                (bindir / tool).symlink_to(real)
        result = self.run_script("--project", "jupiter_sdr", "--dry-run", "--boot-bin", "true",
                                 env={"PATH": str(bindir)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("needs aarch64-linux-gnu-gcc", result.stdout)
        # Explicit bl31.elf never warns, and Zynq-7000 never needs ATF
        result = self.run_script("--project", "jupiter_sdr", "--dry-run", "--boot-bin", "true",
                                 "--boot-bin-atf", "/a/bl31.elf")
        self.assertNotIn("needs aarch64-linux-gnu-gcc", result.stdout)
        result = self.run_script("--project", "pluto", "--release", "hdl_2023_r2", "--dry-run",
                                 "--boot-bin", "true")
        self.assertNotIn("needs aarch64-linux-gnu-gcc", result.stdout)

    def test_missing_boot_bin_helper_is_an_error(self):
        (self.workspace / "scripts/build_zynqmp_boot_bin.sh").unlink()
        result = self.run_script("--project", "jupiter_sdr", "--dry-run", "--boot-bin", "true")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("build_zynqmp_boot_bin.sh is missing", result.stderr)

    def test_carrierless_clean(self):
        mf = self.workspace / "hdl/projects/jupiter_sdr/Makefile"
        # keep the vendor-mk marker so the project is still detected as carrier-less
        mf.write_text("# include ../scripts/project-xilinx.mk\nclean:\n\t@echo CLEANED $(DIR_NAME) in $(CURDIR)\n")
        git(self.workspace / "hdl", "commit", "-qam", "stub clean")
        result = self.run_script("--project", "jupiter_sdr", "--board", "zcu102", "--clean",
                                 "--dir-name", "out")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CLEANED out in " + str(self.workspace / "hdl/projects/jupiter_sdr"), result.stdout)

    def test_clean_of_missing_combo_is_a_noop(self):
        result = self.run_script("--project", "nope", "--board", "zed", "--clean")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nothing to clean", result.stdout)

    def test_clean_runs_project_make_clean(self):
        board_dir = self.workspace / "hdl/projects/cn0561/de10nano"
        (board_dir / "Makefile").write_text("clean:\n\t@echo CLEANED $(DIR_NAME)\n")
        git(self.workspace / "hdl", "commit", "-qam", "stub clean")
        result = self.run_script("--project", "cn0561", "--board", "de10nano", "--clean",
                                 "--dir-name", "out")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CLEANED out", result.stdout)


@unittest.skipUnless(os.environ.get("CIM_NETWORK"), "set CIM_NETWORK=1 to clone the real hdl repo")
class HdlCimWorkspaceTests(unittest.TestCase):
    def test_cim_init_and_generated_makefile(self):
        cim = os.environ.get("CIM_BIN") or shutil.which("cim")
        if not cim:
            self.skipTest("install cim or set CIM_BIN")
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            init = subprocess.run([cim, "init", "--target", "hdl", "--source", str(ROOT),
                                   "--workspace", str(workspace), "--yes"],
                                  text=True, capture_output=True)
            self.assertEqual(init.returncode, 0, init.stdout + init.stderr)
            subprocess.run([cim, "makefile"], cwd=workspace, check=True, capture_output=True)
            makefile = (workspace / "Makefile").read_text()
            self.assertIn("include hdl.mk", makefile)
            self.assertIn("HDL_RELEASE ?= hdl_2026_r1", makefile)
            self.assertTrue((workspace / "scripts/build-hdl.sh").is_file())
            dry = subprocess.run(["make", "-n", "sdk-build", "HDL_RELEASE=hdl_2023_r2"],
                                 cwd=workspace, check=True, text=True, capture_output=True)
            self.assertIn("--release \"hdl_2023_r2\"", dry.stdout)
            listed = subprocess.run(["make", "list-combos", "HDL_RELEASE=hdl_2023_r2"],
                                    cwd=workspace, check=True, text=True, capture_output=True)
            self.assertIn("fmcomms2", listed.stdout)
            head = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=workspace / "hdl",
                                  check=True, text=True, capture_output=True).stdout.strip()
            self.assertEqual(head, "hdl_2023_r2")


if __name__ == "__main__":
    unittest.main()
