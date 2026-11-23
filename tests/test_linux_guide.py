"""Executable offline wizard and generated workspace contracts."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "targets/adi-linux/guide-linux.py"
spec = importlib.util.spec_from_file_location("guide", GUIDE)
assert spec is not None and spec.loader is not None
guide = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guide)


class GuideTests(unittest.TestCase):
    def run_guide(self, *args, text=""):
        return subprocess.run([sys.executable, str(GUIDE), *args], input=text,
                              capture_output=True, text=True, timeout=10)

    def test_information_never_runs_helper(self):
        with patch.object(guide.subprocess, "run", side_effect=AssertionError("execution")):
            for args in (["--list"], ["--dry-run"], ["--dry-run", "--release", "2026_R1"]):
                self.assertEqual(guide.main(args), 0)
        for args in ((), ("--help",), ("--list",)):
            result = self.run_guide(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("xlnx_2026.1.0", self.run_guide("--list").stdout)

    def test_invalid_cli(self):
        for args in (("--release", "bad"), ("--platform", "bad"), ("--jobs", "0"),
                     ("--jobs", "-1"), ("--jobs", "1; touch bad"), ("--output", "\n")):
            self.assertNotEqual(self.run_guide("--dry-run", *args).returncode, 0)

    def test_defaults_retry_list_and_cancel(self):
        # release (?, bad, default) / platform (list, bad, default) / devicetree (default none)
        # / jobs (0 invalid, 'no' invalid, default) / output (default)
        result = self.run_guide("--interactive", "--dry-run",
            text="?\nbad\n\nlist\nbad\n\n\n0\nno\n\n\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Invalid selection", result.stdout)
        self.assertIn("2023_R2", result.stdout)
        self.assertIn("artifacts/2023_R2/zynq", result.stdout)
        self.assertIn("[DRY-RUN]", result.stdout)
        for text in ("", "q\n", "2026_R1\ncancel\n", "\n\n\n\n\n\n"):
            result = self.run_guide("--interactive", text=text)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("cancelled", result.stdout)

    def test_shell_safety_build_and_verify(self):
        path = "output space/$(touch PWNED); 'quoted'"
        for action in ("build", "verify"):
            with patch("builtins.input", side_effect=["2026_R1", "zynqmp", "none", "7", path, action]), \
                 patch.object(guide.subprocess, "run") as run:
                run.return_value.returncode = 17
                self.assertEqual(guide.main(["--interactive"]), 17)
                argv = run.call_args.args[0]
                self.assertEqual(argv[argv.index("--output") + 1], path)
                self.assertEqual("--verify" in argv, action == "verify")
                self.assertNotIn("shell", run.call_args.kwargs)
        result = self.run_guide("--dry-run", "--output", path)
        line = next(x for x in result.stdout.splitlines() if x.startswith("Build command:"))
        argv = shlex.split(line.removeprefix("Build command: "))
        self.assertEqual(argv[-1], path)

    def test_json_output(self):
        # test --list --json
        res_list = self.run_guide("--list", "--json")
        self.assertEqual(res_list.returncode, 0, res_list.stderr)
        import json
        items = json.loads(res_list.stdout)
        self.assertIsInstance(items, list)
        self.assertGreaterEqual(len(items), 4)
        releases = {item["release"] for item in items}
        self.assertIn("2023_R2", releases)
        self.assertIn("2026_R1", releases)

        # test --json configuration export
        res_cfg = self.run_guide("--release", "2026_R1", "--platform", "zynqmp", "--jobs", "8", "--json")
        self.assertEqual(res_cfg.returncode, 0, res_cfg.stderr)
        cfg = json.loads(res_cfg.stdout)
        self.assertEqual(cfg["target"], "adi-linux")
        self.assertEqual(cfg["release"], "2026_R1")
        self.assertEqual(cfg["platform"], "zynqmp")
        self.assertEqual(cfg["arch"], "arm64")
        self.assertEqual(cfg["jobs"], 8)
        self.assertIn("build-kernel.py", cfg["commands"]["build"])
        self.assertIn("build-kernel.py", cfg["commands"]["verify"])

    def test_devicetree_step(self):
        # pick by number from the CSV choices for the platform; output gains /<dts>
        result = self.run_guide("--interactive", "--dry-run", text="2026_R1\nzynqmp\n?\nzynqmp-jupiter-sdr\n\n\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("zynqmp-jupiter-sdr-rx2tx2", result.stdout)          # listed as a choice
        self.assertIn("Devicetree: zynqmp-jupiter-sdr; artifacts in artifacts/2026_R1/zynqmp/zynqmp-jupiter-sdr", result.stdout)
        self.assertIn("--dts zynqmp-jupiter-sdr", result.stdout)
        # non-interactive: --hdl-project resolves through the CSV, ambiguity is an error
        result = self.run_guide("--dry-run", "--release", "2026_R1", "--platform", "zynq", "--hdl-project", "adv7511_zed")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--dts zynq-zed-adv7511", result.stdout)
        result = self.run_guide("--dry-run", "--release", "2026_R1", "--platform", "zynqmp", "--hdl-project", "jupiter_sdr")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("several devicetrees", result.stderr)
        # a devicetree not in the CSV is still accepted (the kernel tree decides)
        result = self.run_guide("--dry-run", "--release", "2026_R1", "--platform", "zynq", "--dts", "zynq-zed-custom")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--dts zynq-zed-custom", result.stdout)

    def test_json_with_devicetree_never_prompts(self):
        import json
        # make config-json passes every variable; empty DTS/HDL_PROJECT means kernel only.
        # stdin is not a tty (and --interactive is ignored), so stdout must be JSON only.
        res = self.run_guide("--interactive", "--release", "2026_R1", "--platform", "zynqmp",
                             "--dts", "zynqmp-jupiter-sdr", "--hdl-project", "", "--json", text="")
        self.assertEqual(res.returncode, 0, res.stderr)
        cfg = json.loads(res.stdout)
        self.assertEqual(cfg["dts"], "zynqmp-jupiter-sdr")
        self.assertEqual(cfg["artifact_dir"], "artifacts/2026_R1/zynqmp/zynqmp-jupiter-sdr")
        self.assertIn("--dts zynqmp-jupiter-sdr", cfg["commands"]["build"])
        # HDL_PROJECT resolves through the CSV exactly like sdk-build does
        res = self.run_guide("--release", "2026_R1", "--platform", "zynq", "--dts", "",
                             "--hdl-project", "adv7511_zed", "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        cfg = json.loads(res.stdout)
        self.assertEqual(cfg["dts"], "zynq-zed-adv7511")
        self.assertIn("--dts zynq-zed-adv7511", cfg["commands"]["build"])
        res = self.run_guide("--release", "2026_R1", "--platform", "zynq", "--dts", "", "--hdl-project", "", "--json")
        self.assertIsNone(json.loads(res.stdout)["dts"])
        self.assertNotIn("--dts", json.loads(res.stdout)["commands"]["build"])
        # ambiguity is an error on stderr, never half-written JSON
        res = self.run_guide("--release", "2026_R1", "--platform", "zynqmp", "--hdl-project", "jupiter_sdr", "--json")
        self.assertNotEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "")
        self.assertIn("several devicetrees", res.stderr)

    def test_generated_target(self):
        cim = os.environ.get("CIM_BIN") or shutil.which("cim")
        if not cim:
            self.skipTest("install cim or set CIM_BIN")
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace space"
            subprocess.run([cim, "init", "--target", "adi-linux", "--source", str(ROOT),
                            "--workspace", str(workspace), "--yes"], check=True, capture_output=True)
            subprocess.run([cim, "makefile"], cwd=workspace, check=True, capture_output=True)
            listed = subprocess.run(["make", "list-dts", "HDL_PROJECT=fmcomms2_zcu102"], cwd=workspace,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertIn("zynqmp-zcu102-rev10-ad9361-fmcomms2-3", listed.stdout)
            dry = subprocess.run(["make", "-n", "sdk-build", "KERNEL_PLATFORM=zynqmp", "KERNEL_DTS=zynqmp-jupiter-sdr"],
                                 cwd=workspace, text=True, capture_output=True, timeout=10)
            self.assertIn('--dts "zynqmp-jupiter-sdr"', dry.stdout)
            self.assertTrue((workspace / "scripts/boot_pairings_2026_r1.csv").is_file())
            for target, text in (("guide-help", ""), ("list-combos", ""),
                                 ("guide-dry-run", "2026_R1\nzynqmp\nnone\n2\noutput space\n"),
                                 ("guide", "cancel\n")):
                result = subprocess.run(["make", target], cwd=workspace, input=text,
                                        text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((workspace / "output space").exists())
            self.assertEqual((workspace / "scripts/guide-linux.py").read_bytes(), GUIDE.read_bytes())


class GuideJsonActionTests(unittest.TestCase):
    def test_json_with_build_or_verify_is_usage_error(self):
        for action in ("--build", "--verify"):
            result = subprocess.run([sys.executable, str(GUIDE), "--release", "2026_R1", "--json", action],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertIn("--json cannot be combined", result.stderr)
            # and in-process: rejected before the helper could ever be launched
            with patch.object(guide.subprocess, "run", side_effect=AssertionError("execution")), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exit_:
                guide.main(["--json", action])
            self.assertEqual(exit_.exception.code, 2)
        # the config export (make config-json) and --json --dry-run keep working
        for extra in ((), ("--dry-run",)):
            result = subprocess.run([sys.executable, str(GUIDE), "--release", "2026_R1", "--json", *extra],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"target": "adi-linux"', result.stdout)


if __name__ == "__main__":
    unittest.main()
