"""Execute the target README's offline examples, not copied test recipes."""
import itertools
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LinuxDocumentationTests(unittest.TestCase):
    def test_documented_offline_commands(self):
        text = (ROOT / "targets/adi-linux/README.md").read_text()
        block = text.split("<!-- linux-offline-examples -->\n```bash\n", 1)[1].split("\n```", 1)[0]
        commands = [shlex.split(line.strip()) for line in block.splitlines()]
        self.assertEqual(len(commands), 5)
        seen = set()
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            scripts = workspace / "scripts"
            scripts.mkdir()
            for name in ("guide-linux.py", "build-kernel.py"):
                shutil.copy(ROOT / "targets/adi-linux" / name, scripts / name)
            for command in commands:
                self.assertEqual(command[:2], ["python3", "scripts/guide-linux.py"])
                self.assertTrue("--list" in command or "--dry-run" in command)
                result = subprocess.run(command, cwd=workspace, input="", text=True,
                                        capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                if "--dry-run" in command:
                    release = command[command.index("--release") + 1]
                    platform = command[command.index("--platform") + 1]
                    seen.add((release, platform))
                    self.assertIn(f"artifacts/{release}/{platform}", result.stdout)
                    self.assertIn("[DRY-RUN] No commands executed.", result.stdout)
                    self.assertIn("--verify", result.stdout)
                else:
                    self.assertEqual(len(result.stdout.splitlines()), 4)
                    self.assertIn("xlnx_2026.1.0", result.stdout)
            self.assertFalse((workspace / "artifacts").exists())
        self.assertEqual(seen, set(itertools.product(("2023_R2", "2026_R1"),
                                                    ("zynq", "zynqmp"))))


if __name__ == "__main__":
    unittest.main()
