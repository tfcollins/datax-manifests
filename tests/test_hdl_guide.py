"""Offline contract tests for targets/hdl/build-hdl.sh release handling."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "targets/hdl/build-hdl.sh"

# Project/board stubs per fake release; the Makefile include decides the tool.
RELEASES = {
    "hdl_2023_r2": {"fmcomms2": {"zed": "xilinx", "zcu102": "xilinx"},
                    "ad9361": {"a10soc": "intel"}},
    "hdl_2026_r1": {"fmcomms2": {"zcu102": "xilinx"},
                    "ad9081_fmca_ebz": {"vck190": "xilinx"},
                    "cn0561": {"de10nano": "intel"}},
}


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
            for board, tool in boards.items():
                board_dir = path / "projects" / project / board
                board_dir.mkdir(parents=True)
                (board_dir / "Makefile").write_text(f"include ../../scripts/project-{tool}.mk\n")
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
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("HDL_RELEASE", "VIVADO", "XILINX_VIVADO")}

    def run_script(self, *args, env=None):
        return subprocess.run(["bash", "scripts/build-hdl.sh", *args], cwd=self.workspace,
                              text=True, capture_output=True, timeout=60,
                              env={**self.env, **(env or {})})

    def head_branch(self):
        return git(self.workspace / "hdl", "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def projects_listed(self, stdout):
        return {line.split("|")[0].strip() for line in stdout.splitlines()
                if "|" in line and not line.startswith("PROJECT")}

    def test_default_release_lists_without_switching(self):
        result = self.run_script("--list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Switching hdl/", result.stdout)
        self.assertEqual(self.projects_listed(result.stdout), set(RELEASES["hdl_2026_r1"]))
        self.assertEqual(self.head_branch(), "hdl_2026_r1")

    def test_release_flag_switches_checkout_and_matrix(self):
        result = self.run_script("--release", "hdl_2023_r2", "--list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Switching hdl/ to release 'hdl_2023_r2'", result.stdout)
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
        self.assertIn("/opt/Xilinx/2023.2/Vivado/settings64.sh", result.stdout)
        self.assertIn("build_boot_bin.sh", result.stdout)
        self.assertFalse((self.workspace / "hdl/projects/fmcomms2/zed/build").exists())

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
