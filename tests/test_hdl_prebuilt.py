"""Tests for prebuilt HDL bitstream and boot artifact helper (targets/hdl/hdl-prebuilt.py)."""

import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "targets/hdl/hdl-prebuilt.py"
BUILD_HDL = ROOT / "targets/hdl/build-hdl.sh"

import importlib.util

spec = importlib.util.spec_from_file_location("hdl_prebuilt", SCRIPT)
hp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hp)


def create_fake_deb(members_dict):
    """Create an in-memory Debian .deb archive with members_dict inside data.tar.gz."""
    # Create data.tar.gz
    data_tar_buf = io.BytesIO()
    with tarfile.open(fileobj=data_tar_buf, mode="w:gz") as tar:
        for name, content in members_dict.items():
            if isinstance(content, str):
                content = content.encode("utf-8")
            ti = tarfile.TarInfo(name=name)
            ti.size = len(content)
            ti.mode = 0o644
            tar.addfile(ti, io.BytesIO(content))
    data_tar_bytes = data_tar_buf.getvalue()

    # Create control.tar.gz
    ctrl_tar_buf = io.BytesIO()
    with tarfile.open(fileobj=ctrl_tar_buf, mode="w:gz") as tar:
        ctrl = b"Package: test\nVersion: 1.0\nArchitecture: all\n"
        ti = tarfile.TarInfo(name="./control")
        ti.size = len(ctrl)
        ti.mode = 0o644
        tar.addfile(ti, io.BytesIO(ctrl))
    ctrl_tar_bytes = ctrl_tar_buf.getvalue()

    deb_binary = b"2.0\n"

    # Assemble ar archive
    def make_ar_header(name, size):
        name_field = f"{name:<16}"[:16].encode("ascii")
        mtime = f"{0:<12}"[:12].encode("ascii")
        uid = f"{0:<6}"[:6].encode("ascii")
        gid = f"{0:<6}"[:6].encode("ascii")
        mode = f"{100644:<8}"[:8].encode("ascii")
        size_field = f"{size:<10}"[:10].encode("ascii")
        fmag = b"`\n"
        return name_field + mtime + uid + gid + mode + size_field + fmag

    out = io.BytesIO()
    out.write(b"!<arch>\n")

    for name, data in [
        ("debian-binary", deb_binary),
        ("control.tar.gz", ctrl_tar_bytes),
        ("data.tar.gz", data_tar_bytes),
    ]:
        hdr = make_ar_header(name, len(data))
        out.write(hdr)
        out.write(data)
        if len(data) % 2 != 0:
            out.write(b"\n")

    return out.getvalue()


class BoundedStreamTests(unittest.TestCase):
    def test_bounded_stream_read_and_seek(self):
        raw_data = b"0123456789abcdefghijklmnopqrstuvwxyz"
        base = io.BytesIO(raw_data)
        base.seek(5)
        # Bounded to 10 bytes starting from offset 5: "56789abcde"
        bs = hp.BoundedStream(base, 10)
        self.assertTrue(bs.readable())
        self.assertTrue(bs.seekable())
        self.assertEqual(bs.tell(), 0)

        chunk1 = bs.read(4)
        self.assertEqual(chunk1, b"5678")
        self.assertEqual(bs.tell(), 4)

        # Seek within bound
        bs.seek(2, io.SEEK_SET)
        self.assertEqual(bs.tell(), 2)
        chunk2 = bs.read(5)
        self.assertEqual(chunk2, b"789ab")

        # Read to end
        bs.seek(8, io.SEEK_SET)
        chunk3 = bs.read(10)
        self.assertEqual(chunk3, b"de")
        self.assertEqual(bs.read(10), b"")


class DebExtractionTests(unittest.TestCase):
    def test_open_deb_data_tar(self):
        fake_deb_bytes = create_fake_deb({
            "./boot/test-board/BOOT.BIN": b"fake bootbin",
            "./boot/test-board/system.dtb": b"fake dtb",
        })
        deb_file = io.BytesIO(fake_deb_bytes)
        members = []
        for tar in hp.open_deb_data_tar(deb_file):
            for m in tar:
                members.append(m.name)
        self.assertIn("./boot/test-board/BOOT.BIN", members)
        self.assertIn("./boot/test-board/system.dtb", members)


class ProjectMatchingTests(unittest.TestCase):
    def setUp(self):
        self.projects = [
            {
                "name": "fmcomms2",
                "board": "zcu102",
                "architecture": "zynqmp",
                "files": [{"path": "/boot/zynqmp-zcu102-rev10-ad936x-fmcomms2-3-4/BOOT.BIN"}],
            },
            {
                "name": "jupiter_sdr",
                "board": "jupiter_sdr",
                "architecture": "zynqmp",
                "files": [{"path": "/boot/zynqmp-jupiter-sdr/BOOT.BIN"}],
            },
            {
                "name": "ad9081",
                "board": "vck190",
                "architecture": "versal",
                "files": [{"path": "/boot/versal-vck190-reva-ad9081/BOOT.BIN"}],
            },
        ]

    def test_exact_match(self):
        matched = hp.match_project(self.projects, "fmcomms2", "zcu102")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["name"], "fmcomms2")
        self.assertEqual(matched["board"], "zcu102")

    def test_carrierless_match(self):
        matched = hp.match_project(self.projects, "jupiter_sdr")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["name"], "jupiter_sdr")

    def test_case_insensitive_and_hyphen_normalization(self):
        matched = hp.match_project(self.projects, "FMCOMMS2", "ZCU-102")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["name"], "fmcomms2")

    def test_unmatched_returns_none(self):
        matched = hp.match_project(self.projects, "nonexistent_project", "zcu102")
        self.assertIsNone(matched)


class PrebuiltExtractionWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.cache_dir = Path(self.tmp_dir) / "cache"
        self.output_dir = Path(self.tmp_dir) / "output"
        self.cache_dir.mkdir()
        self.output_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def test_extract_prebuilt_files(self):
        # Create inner bootgen_sysfiles.tgz
        sysfiles_buf = io.BytesIO()
        with tarfile.open(fileobj=sysfiles_buf, mode="w:gz") as tar:
            for name, content in [
                ("system_top.bit", b"BITSTREAM DATA"),
                ("system_top.xsa", b"XSA DATA"),
                ("zynqmp.bif", b"BIF DATA"),
            ]:
                ti = tarfile.TarInfo(name=name)
                ti.size = len(content)
                tar.addfile(ti, io.BytesIO(content))
        sysfiles_bytes = sysfiles_buf.getvalue()

        # Create deb containing bootgen_sysfiles.tgz, BOOT.BIN and system.dtb
        deb_bytes = create_fake_deb({
            "./boot/zynqmp-zcu102-rev10-ad936x-fmcomms2-3-4/BOOT.BIN": b"BOOTBIN DATA",
            "./boot/zynqmp-zcu102-rev10-ad936x-fmcomms2-3-4/system.dtb": b"DTB DATA",
            "./boot/zynqmp-zcu102-rev10-ad936x-fmcomms2-3-4/bootgen_sysfiles.tgz": sysfiles_bytes,
        })

        deb_path = self.cache_dir / hp.CATALOG["zynqmp"]["filename"]
        deb_path.write_bytes(deb_bytes)

        project_entry = {
            "name": "fmcomms2",
            "board": "zcu102",
            "architecture": "zynqmp",
            "files": [{"path": "/boot/zynqmp-zcu102-rev10-ad936x-fmcomms2-3-4/BOOT.BIN"}],
        }

        # Override verify_file to accept our synthetic deb for testing
        orig_verify = hp.verify_file
        hp.verify_file = lambda p, s: True
        try:
            extracted = hp.extract_prebuilt_files(
                "zynqmp",
                project_entry,
                self.output_dir,
                cache_dir=self.cache_dir,
                project_name="fmcomms2_zcu102",
            )
        finally:
            hp.verify_file = orig_verify

        # Verify extracted contents
        self.assertTrue((self.output_dir / "BOOT.BIN").exists())
        self.assertEqual((self.output_dir / "BOOT.BIN").read_bytes(), b"BOOTBIN DATA")

        self.assertTrue((self.output_dir / "system.dtb").exists())
        self.assertEqual((self.output_dir / "system.dtb").read_bytes(), b"DTB DATA")

        self.assertTrue((self.output_dir / "system_top.bit").exists())
        self.assertEqual((self.output_dir / "system_top.bit").read_bytes(), b"BITSTREAM DATA")

        self.assertTrue((self.output_dir / "system_top.xsa").exists())
        self.assertEqual((self.output_dir / "system_top.xsa").read_bytes(), b"XSA DATA")

        # Verify duplicated XSA in sdk directory for build_boot_bin.sh
        sdk_xsa = self.output_dir / "fmcomms2_zcu102.sdk" / "system_top.xsa"
        self.assertTrue(sdk_xsa.exists())
        self.assertEqual(sdk_xsa.read_bytes(), b"XSA DATA")


class BuildHdlIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        (self.workspace / "hdl/projects/fmcomms2/zcu102").mkdir(parents=True)
        (self.workspace / "hdl/projects/fmcomms2/zcu102/Makefile").write_text(
            "include ../../../scripts/project-xilinx.mk\nPROJECT_NAME := fmcomms2_zcu102\n"
        )
        (self.workspace / "hdl/projects/scripts").mkdir(parents=True)
        (self.workspace / "hdl/projects/scripts/adi_project_xilinx.tcl").write_text(
            'if [regexp "_zcu102" $project_name] {\n  set device "xczu9eg-ffvb1156-2-e"\n}\n'
        )
        (self.workspace / "scripts").mkdir()
        shutil.copy(BUILD_HDL, self.workspace / "scripts/build-hdl.sh")
        shutil.copy(SCRIPT, self.workspace / "scripts/hdl-prebuilt.py")
        for helper in ("build_boot_bin.sh", "build_zynqmp_boot_bin.sh", "build_versal_boot_bin.sh"):
            (self.workspace / "scripts" / helper).write_text("#!/bin/bash\necho STUB $0 $@\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_cli_help_includes_hdl_bitstream(self):
        res = subprocess.run([str(BUILD_HDL), "--help"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("--hdl-bitstream", res.stdout)

    def test_hdl_bitstream_download_dry_run(self):
        # Even without Vivado, --hdl-bitstream download --dry-run should not fail on tool checks
        res = subprocess.run(
            [
                "bash",
                "scripts/build-hdl.sh",
                "--project",
                "fmcomms2",
                "--board",
                "zcu102",
                "--hdl-bitstream",
                "download",
                "--dry-run",
            ],
            cwd=self.workspace,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("[DRY-RUN]", res.stdout)
        self.assertIn("hdl-prebuilt.py", res.stdout)
        self.assertIn("--extract", res.stdout)
        self.assertIn("fmcomms2", res.stdout)

    def test_wizard_prompts_for_prebuilt_and_generates_command(self):
        # Answers: release (Enter), project (fmcomms2), board (zcu102),
        # use prebuilt (Y), jobs (Enter), dir (Enter), BOOT.BIN (y), confirm (n)
        answers = ["", "fmcomms2", "zcu102", "Y", "", "", "y", "n"]
        res = subprocess.run(
            ["bash", "scripts/build-hdl.sh", "--interactive"],
            cwd=self.workspace,
            input="\n".join(answers) + "\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        import re
        plain = re.sub(r"\x1b\[[0-9;]*m", "", res.stdout)
        self.assertIn("HDL Bitstream:         download (ADI Kuiper prebuilt)", plain)
        self.assertIn("HDL_BITSTREAM=download", plain)


class ChecksumValidationTests(unittest.TestCase):
    def test_checksum_mismatch(self):
        tmp = tempfile.NamedTemporaryFile(delete=False)
        try:
            tmp.write(b"bad content")
            tmp.close()
            spec = {"sha256": "0" * 64, "md5": "0" * 32}
            self.assertFalse(hp.verify_file(Path(tmp.name), spec))
        finally:
            os.unlink(tmp.name)


class PrebuiltCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self.tmp.name)
        # Create a mock metadata file for versal
        mock_meta = {
            "projects": [
                {
                    "name": "ad9081",
                    "board": "vck190",
                    "architecture": "versal",
                    "files": [{"path": "/boot/versal-vck190-reva-ad9081/BOOT.BIN"}],
                }
            ]
        }
        (self.cache_dir / "kuiper_versal.json").write_text(json.dumps(mock_meta))

    def tearDown(self):
        self.tmp.cleanup()

    def test_check_project_found(self):
        res = subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "--cache",
                str(self.cache_dir),
                "--arch",
                "versal",
                "--check",
                "--project",
                "ad9081",
                "--board",
                "vck190",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("FOUND", res.stdout)

    def test_check_project_not_found(self):
        res = subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "--cache",
                str(self.cache_dir),
                "--arch",
                "versal",
                "--check",
                "--project",
                "nonexistent_proj",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(res.returncode, 1)
        self.assertIn("NOT FOUND", res.stderr)


if __name__ == "__main__":
    unittest.main()
