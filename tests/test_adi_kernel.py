"""Fast offline contract/security tests; real kernel builds are separate."""
import importlib.util
import io
import itertools
import json
import multiprocessing
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

HELPER = Path(__file__).resolve().parents[1] / "targets/adi-linux/build-kernel.py"
spec = importlib.util.spec_from_file_location("kernel", HELPER)
assert spec is not None and spec.loader is not None
kernel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kernel)


def lock_worker(path, queue):
    with kernel.lock(path):
        queue.put("entered")


class KernelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def payload(self, name):
        data = bytearray(128)
        if name == "zynq":
            data[36:40] = b"\x18\x28\x6f\x01"
        else:
            data[56:60] = b"ARM\x64"
        return bytes(data)

    def artifact(self, name):
        generation = self.root / "image-test"
        generation.mkdir(exist_ok=True)
        path = generation / kernel.TARGETS[name]["output"]
        payload = self.payload(name)
        path.write_bytes(kernel.uimage(payload) if name == "zynq" else payload)
        data = {"schema_version": 1, "platform": name, "kernel_image": str(path),
                "sha256": kernel.digest(path), "provenance": kernel.provenance(name)}
        manifest = self.root / "artifacts.json"
        manifest.write_text(json.dumps(data))
        return manifest, path, data

    def fdt(self, size=64):
        # minimal flattened devicetree: magic + totalsize, zero-padded
        return b"\xd0\x0d\xfe\xed" + struct.pack(">I", size) + bytes(size - 8)

    def test_devicetree_in_manifest(self):
        manifest, path, data = self.artifact("zynqmp")
        dtb = path.parent / "system.dtb"
        dtb.write_bytes(self.fdt())
        data["devicetree"] = {"dts": "zynqmp-jupiter-sdr", "path": str(dtb), "sha256": kernel.digest(dtb)}
        manifest.write_text(json.dumps(data))
        self.assertEqual(kernel.validate_manifest(manifest, "zynqmp", dts="zynqmp-jupiter-sdr")["devicetree"]["dts"],
                         "zynqmp-jupiter-sdr")
        kernel.validate_manifest(manifest, "zynqmp")                      # dts unspecified: still valid
        with self.assertRaisesRegex(ValueError, "not zynqmp-other"):
            kernel.validate_manifest(manifest, "zynqmp", dts="zynqmp-other")
        dtb.write_bytes(self.fdt(72))
        with self.assertRaisesRegex(ValueError, "Devicetree checksum"):
            kernel.validate_manifest(manifest, "zynqmp", dts="zynqmp-jupiter-sdr")
        data["devicetree"]["sha256"] = kernel.digest(dtb)
        dtb.write_bytes(b"not a dtb" + bytes(60))
        data["devicetree"]["sha256"] = kernel.digest(dtb)
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "Invalid flattened devicetree"):
            kernel.validate_manifest(manifest, "zynqmp")
        # kernel-only artifacts cannot satisfy a devicetree request
        manifest2, _, data2 = self.artifact("zynq")
        with self.assertRaisesRegex(ValueError, "built without a devicetree"):
            kernel.validate_manifest(manifest2, "zynq", dts="zynq-zed-adv7511")

    def test_dts_lookup_table(self):
        rows, path, fallback = kernel.load_pairings("2026_R1")
        self.assertEqual(path.name, "boot_pairings_2026_r1.csv")
        self.assertFalse(fallback)
        self.assertTrue(kernel.load_pairings("2023_R2")[2])                 # falls back to the newest CSV
        self.assertEqual({r["platform"] for r in rows if r["FPGA_Type"] == "zynqu"}, {"zynqmp"})
        self.assertEqual(kernel.resolve_dts("2026_R1", "zynq", hdl_project="adv7511_zed"), "zynq-zed-adv7511")
        self.assertEqual(kernel.resolve_dts("2026_R1", "zynq", dts="anything"), "anything")
        for platform, project, message in (("zynqmp", "jupiter_sdr", "several devicetrees"),
                                           ("zynq", "fmcomms2_zcu102", "set KERNEL_PLATFORM=zynqmp"),
                                           ("zynq", "daq2_kcu105", "not buildable by adi-linux"),
                                           ("zynq", "nope", "No devicetree")):
            with self.assertRaisesRegex(ValueError, message):
                kernel.resolve_dts("2026_R1", platform, hdl_project=project)
        with self.assertRaisesRegex(ValueError, "needs --hdl-project"):
            kernel.resolve_dts("2026_R1", "zynq", dts="auto")

    def test_dts_source_layout(self):
        tree = self.root / "linux"
        for sub, name in (("xilinx", "zynq-new"), ("", "zynq-old")):
            d = tree / "arch/arm/boot/dts" / sub
            d.mkdir(parents=True, exist_ok=True)
            (d / (name + ".dts")).write_text("/dts-v1/;\n")
        self.assertEqual(kernel.dts_source(tree, "arm", "zynq-new"), "xilinx")
        self.assertEqual(kernel.dts_source(tree, "arm", "zynq-old"), "")
        with self.assertRaisesRegex(ValueError, "not found under arch/arm/boot/dts"):
            kernel.dts_source(tree, "arm", "zynq-missing")

    def test_git_target_is_self_contained(self):
        self.assertEqual(list(HELPER.parents[1].glob("adi-linux-*-*/")), [])
        manifest = (HELPER.parent / "sdk.yml").read_text()
        self.assertIn("source: build-kernel.py", manifest)
        self.assertNotIn("../", manifest)
        self.assertTrue((HELPER.parent / "os-dependencies.yml").is_file())

    def test_release_selection_and_cache_isolation(self):
        self.assertEqual(kernel.provenance("zynq"), kernel.provenance("zynq", "2023_R2"))
        for name in kernel.TARGETS:
            manifest, image, data = self.artifact(name)
            with self.assertRaisesRegex(ValueError, "provenance"):
                kernel.validate_manifest(manifest, name, "2026_R1")
            data["provenance"] = kernel.provenance(name, "2026_R1")
            manifest.write_text(json.dumps(data))
            result = subprocess.run(["python3", HELPER, "--platform", name,
                                     "--release", "2026_R1", "--output", self.root,
                                     "--verify"], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(data["provenance"]["source"]["ref"], "xlnx_2026.1.0")
            self.assertEqual(data["provenance"]["source"]["ref_type"], "tag")
            with patch.object(kernel, "download", side_effect=RuntimeError("must not download")):
                with self.assertRaisesRegex(ValueError, "provenance"):
                    kernel.build(name, self.root, self.root / "cache", 1)
        self.assertIn(b"ADI Linux 2026_R1", kernel.uimage(self.payload("zynq"), "2026_R1")[:64])

    def test_generated_make_selection(self):
        # Real CIM generation + GNU make expansion, not a hand-written Makefile.
        import os
        cim = os.environ.get("CIM_BIN") or shutil.which("cim")
        if not cim:
            self.skipTest("Set CIM_BIN or install cim for generated-Makefile tests")
        workspace = self.root / "workspace"
        subprocess.run([cim, "init", "--target", "adi-linux", "--source",
                        str(HELPER.parents[2]), "--workspace", str(workspace), "--yes"],
                       check=True, capture_output=True)
        subprocess.run([cim, "makefile"], cwd=workspace, check=True, capture_output=True)
        self.assertEqual((workspace / "scripts/build-kernel.py").read_bytes(), HELPER.read_bytes())
        def recipe(*args):
            return subprocess.run(["make", "-n", "sdk-build", *args], cwd=workspace,
                                  check=True, capture_output=True, text=True).stdout
        default = recipe()
        self.assertIn('--release "2023_R2"', default)
        self.assertIn('--platform "zynq"', default)
        outputs = set()
        for release, name in itertools.product(kernel.RELEASES, kernel.TARGETS):
            text = recipe(f"KERNEL_RELEASE={release}", f"KERNEL_PLATFORM={name}", "KERNEL_JOBS=7")
            output = f"artifacts/{release}/{name}"
            outputs.add(output)
            self.assertIn(f'--release "{release}"', text)
            self.assertIn(f'--platform "{name}"', text)
            self.assertIn(f'--output "{output}"', text)
            self.assertIn('--jobs "7"', text)
            # Explicit synthetic cached-image fixtures exercise the real recipe
            # without pretending to cross-compile a kernel in the offline suite.
            destination = workspace / output
            generation = destination / "image-fixture"
            generation.mkdir(parents=True)
            image = generation / kernel.TARGETS[name]["output"]
            payload = self.payload(name)
            image.write_bytes(kernel.uimage(payload, release) if name == "zynq" else payload)
            manifest = destination / "artifacts.json"
            manifest.write_text(json.dumps({"schema_version": 1, "platform": name,
                "kernel_image": str(image), "sha256": kernel.digest(image),
                "provenance": kernel.provenance(name, release)}))
            subprocess.run(["make", "sdk-build", f"KERNEL_RELEASE={release}",
                            f"KERNEL_PLATFORM={name}", "KERNEL_JOBS=7"], cwd=workspace,
                           check=True, capture_output=True)
            kernel.validate_manifest(manifest, name, release)
        self.assertEqual(len(outputs), 4)
        self.assertIn('--output "custom"', recipe("KERNEL_RELEASE=2026_R1", "KERNEL_PLATFORM=zynqmp", "KERNEL_OUTPUT=custom"))

    def test_invalid_release_rejected(self):
        result = subprocess.run(["python3", HELPER, "--platform", "zynq", "--release",
                                 "xlnx_2026.1.0", "--output", self.root], capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_both_contracts(self):
        for name in kernel.TARGETS:
            manifest, _, data = self.artifact(name)
            self.assertEqual(kernel.validate_manifest(manifest, name), data)
            result = subprocess.run(["python3", HELPER, "--platform", name,
                                     "--output", self.root, "--verify"], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_corrupt_artifact(self):
        manifest, image, _ = self.artifact("zynq")
        image.write_bytes(b"bad")
        with self.assertRaisesRegex(ValueError, "checksum"):
            kernel.validate_manifest(manifest, "zynq")

    def test_provenance_and_schema_fail_closed(self):
        for field, value in [("schema_version", 2), ("platform", "zynqmp"), ("provenance", {})]:
            manifest, _, data = self.artifact("zynq")
            data[field] = value
            manifest.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                kernel.validate_manifest(manifest, "zynq")

    def test_escape_and_symlink_rejected(self):
        manifest, image, data = self.artifact("zynq")
        outside = self.root / "outside"
        shutil.copy(image, outside)
        image.unlink()
        image.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            kernel.validate_manifest(manifest, "zynq")
        data["kernel_image"] = str(outside)
        manifest.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            kernel.validate_manifest(manifest, "zynq")

    def test_cache_rehash_and_failed_download_not_published(self):
        source = self.root / "source"
        source.write_bytes(b"verified")
        spec = {"url": source.as_uri(), "sha256": kernel.digest(source)}
        cache = self.root / "cache"
        downloaded = kernel.download(spec, cache)
        source.unlink()
        self.assertEqual(kernel.download(spec, cache), downloaded)
        downloaded.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "Corrupt"):
            kernel.download(spec, cache)
        downloaded.unlink()
        source.write_bytes(b"wrong")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            kernel.download(spec, cache)
        self.assertFalse(downloaded.exists())
        self.assertFalse(list(cache.glob(".download-*")))

    def test_tar_traversal_and_escaping_symlink(self):
        for kind in ("path", "symlink"):
            archive = self.root / "bad.tar"
            with tarfile.open(archive, "w") as tar:
                entry = tarfile.TarInfo("../escape" if kind == "path" else "link")
                if kind == "symlink":
                    entry.type = tarfile.SYMTYPE
                    entry.linkname = "/etc/passwd"
                tar.addfile(entry, io.BytesIO())
            with self.assertRaises(tarfile.FilterError):
                kernel.extract(archive, self.root / "extract")
        self.assertFalse((self.root / "escape").exists())

    def test_uimage_independent_header_and_mkimage(self):
        _, image, _ = self.artifact("zynq")
        header = struct.unpack(">7I4B32s", image.read_bytes()[:64])
        self.assertEqual(header[4:6], (0x8000, 0x8000))
        self.assertEqual(header[7:11], (5, 2, 2, 0))
        if shutil.which("mkimage"):
            result = subprocess.run(["mkimage", "-l", image], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("00008000", result.stdout)
        image.write_bytes(image.read_bytes()[:-1] + b"x")
        with self.assertRaisesRegex(ValueError, "CRC"):
            kernel.validate_image(image, "zynq")

    def test_lock_serializes_processes(self):
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        path = self.root / "lock"
        with kernel.lock(path):
            process = context.Process(target=lock_worker, args=(path, queue))
            process.start()
            time.sleep(0.1)
            self.assertTrue(queue.empty())
        self.assertEqual(queue.get(timeout=5), "entered")
        process.join(timeout=5)
        self.assertEqual(process.exitcode, 0)

    def test_cache_hit_does_not_build_and_failed_force_preserves_old(self):
        manifest, image, _ = self.artifact("zynq")
        before = manifest.read_bytes(), image.read_bytes()
        with patch.object(kernel, "download", side_effect=RuntimeError("offline")):
            self.assertEqual(kernel.build("zynq", self.root, self.root / "cache", 1), manifest)
            with self.assertRaises(RuntimeError):
                kernel.build("zynq", self.root, self.root / "cache", 1, force=True)
        self.assertEqual((manifest.read_bytes(), image.read_bytes()), before)

    def test_build_commands_publication_and_generation_replacement(self):
        for name, release in itertools.product(kernel.TARGETS, kernel.RELEASES):
            output = self.root / release / name
            commands = []

            def extract(_archive, destination):
                if destination.name == "source":
                    (destination / ("linux-" + kernel.RELEASES[release]["commit"])).mkdir(parents=True)
                else:
                    compiler = destination / "bin" / (kernel.TARGETS[name]["triple"] + "-gcc")
                    compiler.parent.mkdir(parents=True)
                    compiler.touch()

            def run(command, env):
                commands.append(command)
                build = Path(next(x[2:] for x in command if isinstance(x, str) and x.startswith("O=")))
                image = build / "arch" / kernel.TARGETS[name]["arch"] / "boot" / kernel.TARGETS[name]["image"]
                image.parent.mkdir(parents=True, exist_ok=True)
                image.write_bytes(self.payload(name))
                self.assertNotIn("MAKEFLAGS", env)

            with patch.object(kernel, "download", return_value=self.root / "archive"), patch.object(kernel, "extract", side_effect=extract), patch.object(kernel, "run", side_effect=run):
                manifest = kernel.build(name, output, self.root / "cache", 2, release=release)
                first = kernel.validate_manifest(manifest, name, release)
                kernel.build(name, output, self.root / "cache", 2, force=True, release=release)
                second = kernel.validate_manifest(manifest, name, release)
            self.assertNotEqual(first["kernel_image"], second["kernel_image"])
            self.assertTrue(Path(first["kernel_image"]).is_file())
            self.assertEqual(commands[0][-1], kernel.TARGETS[name]["defconfig"])
            self.assertEqual(commands[1][-2:], ["-j2", kernel.TARGETS[name]["image"]])
            self.assertFalse(list(output.glob(".build-*")))


if __name__ == "__main__":
    unittest.main()
