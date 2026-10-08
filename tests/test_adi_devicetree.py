"""Devicetree builds for the adi-linux platforms.

The sweep tests compile every zynq / zynqmp row of the boot-pairings CSV from
the pinned 2026_R1 kernel (and a representative set from 2023_R2) with the
real toolchain: they need network for the archives (cached afterwards) and run
only with CIM_NETWORK=1. The offline tests cover the CLI contract."""
import importlib.util
import os
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

HELPER = Path(__file__).resolve().parents[1] / "targets/adi-linux/build-kernel.py"
spec = importlib.util.spec_from_file_location("kernel", HELPER)
kernel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kernel)

CACHE = Path(os.environ.get("CIM_ADI_LINUX_CACHE", Path.home() / ".cache/cim/adi-linux"))
JOBS = os.cpu_count() or 2


def helper(*args, **kwargs):
    return subprocess.run(["python3", str(HELPER), *args], text=True, capture_output=True, **kwargs)


class DtbOnlyCli(unittest.TestCase):
    def test_needs_dts(self):
        result = helper("--dtb-only", "--platform", "zynq", "--output", "x")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--dtb-only needs --dts", result.stderr)

    def test_all_expands_to_platform_rows(self):
        rows, _, _ = kernel.load_pairings("2026_R1")
        for platform, kind, unique in (("zynq", "zynq", 67), ("zynqmp", "zynqu", 49)):
            names = [r["DTS"] for r in kernel.find_dts(rows, platform=platform)]
            self.assertEqual(len(names), sum(1 for r in rows if r["FPGA_Type"] == kind))
            # a devicetree may serve several HDL variants (adrv9002 CMOS/LVDS); the sweep builds each once
            self.assertEqual(len(set(names)), unique, platform)

    def test_make_dtb_target(self):
        with tempfile.TemporaryDirectory() as directory:
            ws = Path(directory)
            (ws / "Makefile").write_text("KERNEL_RELEASE ?= 2026_R1\nKERNEL_PLATFORM ?= zynq\nKERNEL_DTS ?= \n"
                                         "KERNEL_OUTPUT ?= out\nKERNEL_JOBS ?= 2\ninclude linux.mk\n")
            (ws / "linux.mk").write_bytes((HELPER.parent / "linux.mk").read_bytes())
            dry = subprocess.run(["make", "-n", "dtb", "KERNEL_PLATFORM=zynqmp", "KERNEL_DTS=all"], cwd=ws,
                                 text=True, capture_output=True)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertIn('--dtb-only --release "2026_R1" --platform "zynqmp"', dry.stdout)
            self.assertIn('--dts "all"', dry.stdout)


@unittest.skipUnless(os.environ.get("CIM_NETWORK"), "set CIM_NETWORK=1 to download the pinned kernel and compile devicetrees")
class DevicetreeSweep(unittest.TestCase):
    """Every CSV devicetree for the platform must exist in the kernel tree and compile."""

    def sweep(self, release, platform, names):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            # Resolve all names first so a bad CSV row reports every missing DTS at once.
            with tempfile.TemporaryDirectory() as temporary, \
                    kernel.configured_tree(platform, release, CACHE, temporary) as (source, _, _):
                missing = []
                for dts in names:
                    try:
                        kernel.dts_source(source, kernel.TARGETS[platform]["arch"], dts)
                    except ValueError:
                        missing.append(dts)
            self.assertEqual(missing, [], f"{release}/{platform}: devicetrees not in the kernel tree")
            built = kernel.build_dtbs(platform, release, names, output, CACHE, JOBS)
            self.assertEqual(sorted(built), sorted(names))
            for dts, dtb in built.items():
                self.assertEqual(dtb.name, kernel.DTB_NAME[platform])
                data = dtb.read_bytes()
                self.assertEqual(data[:4], kernel.DTB_MAGIC, dts)
                self.assertEqual(struct.unpack(">I", data[4:8])[0], len(data), dts)
                self.assertGreater(len(data), 4096, dts)   # a real board DT, not an empty stub
                self.assertIn(b"compatible", data, dts)

    @staticmethod
    def csv_names(platform):
        rows, _, _ = kernel.load_pairings("2026_R1")
        return list(dict.fromkeys(r["DTS"] for r in kernel.find_dts(rows, platform=platform)))

    def test_2026_r1_zynq_all(self):
        names = self.csv_names("zynq")
        self.assertEqual(len(names), 67)
        self.sweep("2026_R1", "zynq", names)

    def test_2026_r1_zynqmp_all(self):
        names = self.csv_names("zynqmp")
        self.assertEqual(len(names), 49)
        self.sweep("2026_R1", "zynqmp", names)

    def test_2023_r2_representative(self):
        # The CSV is 2026_R1's; the older tree keeps the long-standing boards.
        self.sweep("2023_R2", "zynq", ["zynq-zed-adv7511-ad9361-fmcomms2-3", "zynq-zc706-adv7511-fmcdaq2"])
        self.sweep("2023_R2", "zynqmp", ["zynqmp-jupiter-sdr", "zynqmp-zcu102-rev10-ad9361-fmcomms2-3"])


if __name__ == "__main__":
    unittest.main()
