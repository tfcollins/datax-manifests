"""Offline contract tests for targets/hdl/build-hdl.sh release handling."""
import json
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

    def stub_vivado(self):
        """Fake Vivado install so require_tool_installed passes without the real thing."""
        viv = self.workspace / "fake-vivado"
        viv.mkdir()
        (viv / "settings64.sh").write_text("# stub\n")
        return str(viv)

    def test_build_failure_propagates(self):
        board_dir = self.workspace / "hdl/projects/cn0561/de10nano"   # intel: stub QUARTUS_ROOTDIR
        (board_dir / "Makefile").write_text("include ../../../scripts/project-intel.mk\nall:\n\t@echo BUILD FAILED; exit 3\n")
        git(self.workspace / "hdl", "commit", "-qam", "failing stub")
        fake_quartus = self.workspace / "fake-quartus"
        fake_quartus.mkdir(exist_ok=True)
        result = self.run_script("--project", "cn0561", "--board", "de10nano",
                                 env={"QUARTUS_ROOTDIR": str(fake_quartus)})
        self.assertNotEqual(result.returncode, 0)          # make reports 2 for a failed recipe
        self.assertIn("[FAILED] HDL build of cn0561/de10nano exited with status 2", result.stderr)
        self.assertNotIn("[SUCCESS]", result.stdout)

    def test_make_command_line_overrides_do_not_leak_into_hdl(self):
        # The hdl tree defines its own VIVADO; a workspace-level 'make sdk-build VIVADO=auto'
        # puts VIVADO=auto into MAKEFLAGS and used to clobber it ("/bin/sh: auto: not found").
        board_dir = self.workspace / "hdl/projects/fmcomms2/zcu102"
        (board_dir / "Makefile").write_text(
            "VIVADO := vivado -mode batch -source\ninclude ../../scripts/project-xilinx.mk\n"
            "all:\n\t@echo HDL_VIVADO=[$(VIVADO)] HDL_PROJECT=[$(HDL_PROJECT)] FLAGS=[$(MAKEFLAGS)]\n")
        (self.workspace / "hdl/projects/scripts/project-xilinx.mk").write_text("# stub\n")
        git(self.workspace / "hdl", "add", "-A")
        git(self.workspace / "hdl", "commit", "-qm", "echo stub")
        viv = self.stub_vivado()
        (self.workspace / "Makefile").write_text(
            "VIVADO ?= auto\nHDL_PROJECT ?= fmcomms2\nHDL_BOARD ?= zcu102\n"
            "sdk-build:\n\tbash scripts/build-hdl.sh --vivado \"$(VIVADO)\" --project \"$(HDL_PROJECT)\" --board \"$(HDL_BOARD)\" --jobs 1\n")
        result = subprocess.run(["make", "-s", "sdk-build", f"VIVADO={viv}", "HDL_PROJECT=fmcomms2", "HDL_BOARD=zcu102"],
                                cwd=self.workspace, text=True, capture_output=True, env=self.env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("HDL_VIVADO=[vivado -mode batch -source]", result.stdout)
        self.assertNotIn("VIVADO=", result.stdout.split("FLAGS=[")[1].split("]")[0])
        # and with BOOT.BIN enabled the helper is actually invoked after the build
        (self.workspace / "scripts/build_zynqmp_boot_bin.sh").write_text("#!/bin/bash\necho BOOTBIN-HELPER $1 $2 $3\n")
        result = self.run_script("--project", "fmcomms2", "--board", "zcu102", "--vivado", viv, "--jobs", "1",
                                 "--boot-bin", "true", "--boot-bin-uboot", "/u.elf", "--boot-bin-atf", "/b.elf")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Generating BOOT.BIN [zynqmp]", result.stdout)
        self.assertIn("BOOTBIN-HELPER build/fmcomms2_zcu102.sdk/system_top.xsa /u.elf /b.elf", result.stdout)
        self.assertIn("[SUCCESS]", result.stdout)

    def test_missing_vivado_is_an_error_not_a_late_127(self):
        result = self.run_script("--project", "fmcomms2", "--board", "zcu102", "--vivado", "/nonexistent/Vivado")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Vivado not found", result.stderr)
        self.assertIn("VIVADO=", result.stderr)
        self.assertNotIn("[SUCCESS]", result.stdout)
        # dry-run still works without the tool installed
        result = self.run_script("--project", "fmcomms2", "--board", "zcu102", "--vivado", "/nonexistent/Vivado", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)

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
        # --dry-run only prints the clean command
        result = self.run_script("--project", "cn0561", "--board", "de10nano", "--clean",
                                 "--dir-name", "out", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("CLEANED", result.stdout)
        self.assertIn('DIR_NAME="out" clean', result.stdout)

    def test_list_json(self):
        result = self.run_script("--list", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertIsInstance(data, list)
        self.assertTrue(any(c["project"] == "fmcomms2" and c["board"] == "zcu102" for c in data))
        self.assertTrue(any(c["project"] == "jupiter_sdr" and c["is_carrierless"] for c in data))

    def test_list_projects_json(self):
        result = self.run_script("--list-projects", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertIsInstance(data, list)
        self.assertIn("fmcomms2", data)
        self.assertIn("jupiter_sdr", data)

    def test_list_boards_json(self):
        result = self.run_script("--list-boards", "fmcomms2", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertIsInstance(data, list)
        self.assertIn("zcu102", data)

    def test_check_tools_json(self):
        result = self.run_script("--check-tools", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertIn("release", data)
        self.assertIn("vivado", data)
        self.assertIn("quartus", data)
        self.assertIn("radiant", data)

    def test_dry_run_json(self):
        result = self.run_script("--project", "fmcomms2", "--board", "zcu102", "--boot-bin", "--dry-run", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["target"], "hdl")
        self.assertEqual(data["project"], "fmcomms2")
        self.assertEqual(data["board"], "zcu102")
        self.assertEqual(data["tool"]["name"], "Vivado")
        self.assertEqual(data["boot_arch"], "zynqmp")
        self.assertTrue(data["boot_bin"]["enabled"])
        self.assertIn("make", data["commands"]["build"])

    def test_list_boards_json_unknown_project_fails(self):
        # Text mode exits 1 for an unknown project; JSON must not answer "[]" with 0
        text = self.run_script("--list-boards", "nope")
        self.assertEqual(text.returncode, 1)
        for args in (("--list-boards", "nope", "--json"), ("-p", "nope", "--json")):
            result = self.run_script(*args)
            self.assertNotEqual(result.returncode, 0, args)
            self.assertEqual(result.stdout, "", args)
            self.assertIn("'nope' not found", result.stderr)
        # carrier-less projects still answer an empty list
        result = self.run_script("--list-boards", "jupiter_sdr", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])

    def test_check_tools_json_fails_like_text_without_vivado(self):
        git(self.upstream, "branch", "hdl_experimental", "hdl_2026_r1")
        text = self.run_script("--check-tools", "--release", "hdl_experimental")
        self.assertNotEqual(text.returncode, 0)
        result = self.run_script("--check-tools", "--json", "--release", "hdl_experimental")
        self.assertEqual(result.returncode, text.returncode, result.stderr)
        data = json.loads(result.stdout)            # still a full report on stdout
        self.assertEqual(data["release"], "hdl_experimental")
        self.assertIsNone(data["vivado"]["version"])
        self.assertIn("VIVADO=", result.stderr)
        result = self.run_script("--check-tools", "--json", "--release", "hdl_experimental",
                                 "--vivado", "/x/y/2025.1/Vivado")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["vivado"]["version"], "2025.1")

    def test_invalid_board_json_keeps_stdout_clean(self):
        result = self.run_script("-p", "fmcomms2", "-b", "nope", "--dry-run", "--json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("Available boards for project", result.stderr)
        self.assertIn("  - zcu102", result.stderr)
        # text mode unchanged
        result = self.run_script("-p", "fmcomms2", "-b", "nope", "--dry-run")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Available boards for project", result.stdout)

    def test_dry_run_json_boot_bin_matches_text_dry_run(self):
        args = ("--project", "fmcomms2", "--board", "zcu102", "--boot-bin", "--dry-run",
                "--boot-bin-uboot", "/u/u-boot.elf", "--boot-bin-atf", "/a/bl31.elf")
        text = self.run_script(*args)
        self.assertEqual(text.returncode, 0, text.stderr)
        line = next(l for l in text.stdout.splitlines() if l.startswith("3) "))
        text_cmd = line[3:].split("   # BOOT.BIN")[0]
        data = json.loads(self.run_script(*args, "--json").stdout)
        project_dir = str(self.workspace / "hdl/projects/fmcomms2/zcu102")
        self.assertTrue(data["commands"]["boot_bin"].startswith(f'cd "{project_dir}" && bash '))
        self.assertEqual(data["commands"]["boot_bin"], text_cmd)
        self.assertEqual(data["commands"]["boot_bin_source"], "helper")
        self.assertEqual(data["boot_bin"]["command"], data["commands"]["boot_bin"])
        # no BOOT.BIN requested: no command at all
        data = json.loads(self.run_script("--project", "fmcomms2", "--board", "zcu102",
                                          "--dry-run", "--json").stdout)
        self.assertIsNone(data["commands"]["boot_bin"])
        self.assertIsNone(data["commands"]["boot_bin_source"])

    def test_dry_run_json_all_prebuilt_boot_bin_is_unpacked_not_built(self):
        base = ("--project", "jupiter_sdr", "--boot-bin", "--hdl-bitstream", "download", "--dry-run")
        data = json.loads(self.run_script(*base, "--json").stdout)
        self.assertIsNone(data["commands"]["boot_bin"])
        self.assertEqual(data["commands"]["boot_bin_source"], "prebuilt")
        self.assertEqual(data["boot_bin"]["source"], "prebuilt")
        self.assertNotIn("boot_bin.sh", json.dumps(data["commands"]))
        text = self.run_script(*base)
        self.assertIn("Prebuilt BOOT.BIN unpacked", text.stdout)
        # a u-boot from source still runs the packaging helper, also with a prebuilt bitstream
        data = json.loads(self.run_script(*base, "--boot-bin-uboot", "/u/u-boot.elf", "--json").stdout)
        self.assertEqual(data["commands"]["boot_bin_source"], "helper")
        self.assertIn("build_zynqmp_boot_bin.sh", data["commands"]["boot_bin"])
        self.assertTrue(data["commands"]["boot_bin"].startswith("cd \""))
        # and so does a source bitstream with downloaded u-boot/ATF
        data = json.loads(self.run_script("--project", "jupiter_sdr", "--boot-bin", "--dry-run", "--json").stdout)
        self.assertEqual(data["commands"]["boot_bin_source"], "helper")

    def stub_make_targets(self):
        board_dir = self.workspace / "hdl/projects/cn0561/de10nano"
        (board_dir / "Makefile").write_text("-include ../../scripts/project-intel.mk\n"
                                            "all:\n\t@echo BUILT\nclean:\n\t@echo CLEANED\n")
        git(self.workspace / "hdl", "commit", "-qam", "stub build/clean")
        fake_quartus = self.workspace / "fake-quartus"
        fake_quartus.mkdir(exist_ok=True)
        return {"QUARTUS_ROOTDIR": str(fake_quartus)}

    def test_json_with_a_real_action_is_a_usage_error(self):
        env = self.stub_make_targets()
        combo = ("--project", "cn0561", "--board", "de10nano")
        for extra in ((), ("--clean",), ("--hdl-bitstream", "download")):
            result = self.run_script(*combo, *extra, "--json", env=env)
            self.assertEqual(result.returncode, 2, (extra, result.stderr))
            self.assertEqual(result.stdout, "", extra)
            self.assertIn("--json cannot be combined", result.stderr)
        # carrier-less: --project alone is a build too
        result = self.run_script("--project", "jupiter_sdr", "--json")
        self.assertEqual(result.returncode, 2, result.stderr)
        # rejected before hdl/ is switched to another release
        result = self.run_script("--release", "hdl_2023_r2", *combo, "--json", env=env)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.head_branch(), "hdl_2026_r1")
        # --interactive never prompts under --json
        result = self.run_script("--interactive", "--json", input="fmcomms2\n")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        # queries stay allowed
        for args in (("--project", "fmcomms2", "--json"), (*combo, "--dry-run", "--json"),
                     (*combo, "--clean", "--dry-run", "--json")):
            result = self.run_script(*args, env=env)
            self.assertEqual(result.returncode, 0, (args, result.stderr))
            json.loads(result.stdout)
            self.assertNotIn("BUILT", result.stdout)
            self.assertNotIn("CLEANED", result.stdout)
        self.assertEqual(json.loads(self.run_script(*combo, "--clean", "--dry-run", "--json",
                                                    env=env).stdout)["action"], "clean")
        # text mode still builds / cleans
        self.assertIn("BUILT", self.run_script(*combo, env=env).stdout)
        self.assertIn("CLEANED", self.run_script(*combo, "--clean", env=env).stdout)

    def test_clean_json_of_missing_combo_fails(self):
        result = self.run_script("--project", "nope", "--board", "zed", "--clean", "--dry-run", "--json")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("does not exist", result.stderr)
        result = self.run_script("--project", "nope", "--board", "zed", "--clean", "--json")
        self.assertEqual(result.returncode, 2)


class HdlBootWizardTests(HdlGuideTests):
    """The same wizard in an hdl-boot workspace: plans u-boot/ATF and drives make."""

    def setUp(self):
        super().setUp()
        for name, target in (("build-uboot.sh", "u-boot-xlnx"), ("build-atf.sh", "arm-trusted-firmware")):
            shutil.copy(ROOT / "targets" / target / name, self.workspace / "scripts" / name)
        for repo in ("u-boot-xlnx", "arm-trusted-firmware"):
            d = self.workspace / repo
            d.mkdir()
            git(d, "init", "-q")
        shutil.copy(ROOT / "targets/hdl-boot/boot.mk", self.workspace / "boot.mk")
        # Stand-in for cim's generated Makefile: record what sdk-build was asked to do
        (self.workspace / "Makefile").write_text(
            "sdk-build:\n\t@echo MAKE sdk-build HDL_RELEASE=$(HDL_RELEASE) HDL_PROJECT=$(HDL_PROJECT) "
            "HDL_BOARD=$(HDL_BOARD) BUILD_BOOT_BIN=$(BUILD_BOOT_BIN) BOOT_BIN_UBOOT=$(BOOT_BIN_UBOOT) "
            "BOOT_BIN_ATF=$(BOOT_BIN_ATF)\n")

    # Inherited wizard tests still pass with the boot helpers present, except that
    # the BOOT.BIN prompt now defaults to yes: re-state the one that answered it.
    def test_wizard_offers_boot_bin_for_zynq_designs_only(self):
        result = self.wizard(["", "jupiter_sdr", "", "", "", "", "n"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Generate BOOT.BIN:     true (zynqmp)", result.stdout)
        result = self.wizard(["", "fmcomms2", "kcu105", "", "", "n"])
        self.assertIn("not applicable", result.stdout)
        self.assertNotIn("Boot components", result.stdout)

    def test_wizard_plans_boot_components_from_the_design(self):
        # jupiter: ZynqMP, u-boot preset by project, ATF tag from the release; default = from source
        result = self.wizard(["", "jupiter_sdr", "", "", "", "", "n"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("u-boot:  jupiter-sdr / xilinx_zynqmp_virt_defconfig / zynqmp-jupiter-sdr", result.stdout)
        self.assertIn("ATF:     zynqmp @ xilinx-v2025.1", result.stdout)
        self.assertIn("Boot components:       from source", result.stdout)
        self.assertNotIn("BOOT_BIN_UBOOT=download", result.stdout)
        # zed on 2023_r2: Zynq-7000 -> no ATF, u-boot tag follows the release; choose download
        result = self.wizard(["hdl_2023_r2", "fmcomms2", "zed", "", "", "", "n", "n"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("u-boot:  xlnx_rebase_v2023.01_2023.2 / xilinx_zynq_virt_defconfig / zynq-zed", result.stdout)
        self.assertIn("ATF:     not needed (Zynq-7000)", result.stdout)
        self.assertIn("Boot components:       ADI prebuilt download", result.stdout)
        self.assertIn("BUILD_BOOT_BIN=true BOOT_BIN_UBOOT=download BOOT_BIN_ATF=download sdk-build", result.stdout)

    def test_wizard_warns_when_no_uboot_preset(self):
        # Give the fake repo a ZynqMP carrier with no u-boot preset
        board_dir = self.workspace / "hdl/projects/fmcomms2/zcu106"
        board_dir.mkdir()
        (board_dir / "Makefile").write_text("PROJECT_NAME := fmcomms2_zcu106\ninclude ../../scripts/project-xilinx.mk\n")
        with (self.workspace / "hdl/projects/scripts/adi_project_xilinx.tcl").open("a") as f:
            f.write('if [regexp "_zcu106" $project_name] {\n  set device "xczu7ev-ffvc1156-2-e"\n}\n')
        git(self.workspace / "hdl", "add", "-A")
        git(self.workspace / "hdl", "commit", "-qm", "zcu106")
        result = self.wizard(["", "fmcomms2", "zcu106", "", "", "", "n"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No u-boot preset for fmcomms2/zcu106", result.stdout)
        self.assertIn("UBOOT_REF", result.stdout)
        self.assertNotIn("Build u-boot and ATF from source?", result.stdout)

    def test_wizard_executes_through_make_so_components_build_first(self):
        result = self.wizard(["", "jupiter_sdr", "", "", "", "", "y"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MAKE sdk-build HDL_RELEASE=hdl_2026_r1 HDL_PROJECT=jupiter_sdr HDL_BOARD= BUILD_BOOT_BIN=true "
                      "BOOT_BIN_UBOOT= BOOT_BIN_ATF=", result.stdout)
        result = self.wizard(["", "fmcomms2", "zcu102", "", "", "", "n", "y"])
        self.assertIn("HDL_PROJECT=fmcomms2 HDL_BOARD=zcu102 BUILD_BOOT_BIN=true "
                      "BOOT_BIN_UBOOT=download BOOT_BIN_ATF=download", result.stdout)

    def test_boot_mk_skips_components_when_not_needed(self):
        (self.workspace / "Makefile").write_text(
            "HDL_RELEASE ?= hdl_2026_r1\nHDL_PROJECT ?= fmcomms2\nHDL_BOARD ?= zcu102\nBUILD_BOOT_BIN ?= true\n"
            "BOOT_BIN_UBOOT ?= $(CURDIR)/u-boot-xlnx/u-boot.elf\nBOOT_BIN_ATF ?= $(CURDIR)/arm-trusted-firmware/bl31.elf\n"
            "UBOOT_BOARD ?= auto\nATF_PLAT ?= auto\nATF_CONSOLE ?= cadence0\ninclude boot.mk\n")
        def mk(*args):
            return subprocess.run(["make", *args], cwd=self.workspace, text=True, capture_output=True, env=self.env)
        r = mk("boot-uboot", "BUILD_BOOT_BIN=false")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("u-boot: skipped", r.stdout)
        r = mk("boot-atf", "BOOT_BIN_ATF=download")
        self.assertIn("ATF: skipped", r.stdout)
        r = mk("boot-atf", "HDL_PROJECT=fmcomms2", "HDL_BOARD=zed", "HDL_RELEASE=hdl_2023_r2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ATF: not needed for a Zynq-7000 design", r.stdout)
        r = mk("boot-atf", "HDL_PROJECT=fmcomms2", "HDL_BOARD=kcu105")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("set ATF_PLAT", r.stderr)

    def boot_make(self, *args):
        (self.workspace / "Makefile").write_text(
            "HDL_RELEASE ?= hdl_2026_r1\nHDL_PROJECT ?= fmcomms2\nHDL_BOARD ?= zcu102\nBUILD_BOOT_BIN ?= true\n"
            "BOOT_BIN_UBOOT ?= $(CURDIR)/u-boot-xlnx/u-boot.elf\nBOOT_BIN_ATF ?= $(CURDIR)/arm-trusted-firmware/bl31.elf\n"
            "UBOOT_BOARD ?= auto\nUBOOT_REF ?=\nUBOOT_DEFCONFIG ?=\nUBOOT_DEVICE_TREE ?=\n"
            "ATF_PLAT ?= auto\nATF_REF ?=\nATF_CONSOLE ?= cadence0\ninclude boot.mk\n")
        return subprocess.run(["make", "-s", *args], cwd=self.workspace, text=True, capture_output=True, env=self.env)

    def test_boot_config_json_non_bootable_design(self):
        r = self.boot_make("boot-config-json", "HDL_PROJECT=fmcomms2", "HDL_BOARD=kcu105")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["boot_arch"], "none")          # not "none\nnone"
        self.assertIsNone(data["uboot"])
        self.assertIsNone(data["atf"])

    def test_boot_config_json_zynq_has_no_atf(self):
        r = self.boot_make("boot-config-json", "HDL_PROJECT=fmcomms2", "HDL_BOARD=zed", "HDL_RELEASE=hdl_2023_r2")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["boot_arch"], "zynq")
        self.assertEqual(data["uboot"]["defconfig"], "xilinx_zynq_virt_defconfig")
        self.assertIsNone(data["atf"])

    def test_boot_config_json_unresolvable_uboot_is_null_with_message(self):
        r = self.boot_make("boot-config-json", "UBOOT_BOARD=bogus")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertIsNone(data["uboot"])
        self.assertIn("u-boot could not be resolved", r.stderr)
        self.assertEqual(data["boot_arch"], "zynqmp")
        self.assertEqual(data["atf"]["plat"], "zynqmp")

    def test_boot_config_json_passes_the_recipes_overrides(self):
        overrides = ("UBOOT_REF=my-uboot-ref", "UBOOT_DEFCONFIG=my_defconfig", "UBOOT_DEVICE_TREE=my-dt",
                     "ATF_REF=my-atf-ref")
        r = self.boot_make("boot-config-json", *overrides)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["uboot"]["ref"], "my-uboot-ref")
        self.assertEqual(data["uboot"]["defconfig"], "my_defconfig")
        self.assertEqual(data["uboot"]["device_tree"], "my-dt")
        self.assertEqual(data["atf"]["ref"], "my-atf-ref")
        # ... which are exactly what the real recipes pass
        uboot = self.boot_make("-n", "boot-uboot", *overrides).stdout
        for flag in ('--ref "my-uboot-ref"', '--defconfig "my_defconfig"', '--device-tree "my-dt"'):
            self.assertIn(flag, uboot)
        self.assertIn('--ref "my-atf-ref"', self.boot_make("-n", "boot-atf", *overrides).stdout)

    def test_boot_dry_run_honours_overrides(self):
        r = self.boot_make("boot-dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("checkout xlnx_rebase_v2025.01_2025.1", r.stdout)
        self.assertIn("checkout xilinx-v2025.1", r.stdout)
        r = self.boot_make("boot-dry-run", "UBOOT_REF=my-uboot-ref", "ATF_REF=my-atf-ref")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("u-boot-xlnx\" checkout my-uboot-ref", r.stdout)
        self.assertIn("arm-trusted-firmware\" checkout my-atf-ref", r.stdout)
        r = self.boot_make("boot-dry-run", "HDL_PROJECT=fmcomms2", "HDL_BOARD=zed", "HDL_RELEASE=hdl_2023_r2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ATF: not needed (zynq)", r.stdout)


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


class WorkspaceDiscoveryTests(unittest.TestCase):
    """The upward search must not adopt an unrelated hdl/ checkout in an ancestor."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name) / "parent"
        (self.parent / "hdl/projects/x").mkdir(parents=True)     # not a git repo: nothing to switch
        self.checkout = self.parent / "checkout"
        (self.checkout / "tools").mkdir(parents=True)
        shutil.copy(SCRIPT, self.checkout / "tools/build-hdl.sh")
        self.env = {k: v for k, v in os.environ.items() if k not in ("HDL_RELEASE", "VIVADO", "XILINX_VIVADO")}

    def run_script(self, *args):
        return subprocess.run(["bash", "tools/build-hdl.sh", *args], cwd=self.checkout, text=True,
                              capture_output=True, timeout=30, env=self.env)

    def test_ancestor_hdl_without_workspace_marker_is_ignored(self):
        result = self.run_script("--list-projects")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Could not locate hdl/projects", result.stderr)
        self.assertNotIn("x", result.stdout.split())

    def test_ancestor_cim_workspace_is_found(self):
        (self.parent / ".workspace").write_text("workspace_version: 1\n")
        result = self.run_script("--list-projects")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("x", result.stdout.split())


if __name__ == "__main__":
    unittest.main()
