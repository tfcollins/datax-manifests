#!/usr/bin/env python3
"""Pinned ADI kernel builder. Linux x86_64, Python >= 3.11 (stdlib only)."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zlib

COMMIT = "86d61468a7856e952c7ca237f798d86d6abd2e27"
SOURCE = {
    "url": f"https://codeload.github.com/analogdevicesinc/linux/tar.gz/{COMMIT}",
    "sha256": "d8303eb5d0d2e002017768ff89661e2f97be0bd5dd8842db2210826791148dcb",
    "commit": COMMIT, "ref": "2023_R2",
}
BASE = "https://mirrors.edge.kernel.org/pub/tools/crosstool/files/bin/x86_64/12.2.0/"
RELEASES = {
    "2023_R2": SOURCE,
    "2026_R1": {
        "url": "https://codeload.github.com/analogdevicesinc/linux/tar.gz/b47bbbe8ca7bc582c96251fa30d86e55de363f68",
        "sha256": "0886274c27356de24e3b7030817e1669d1e14b42a17a2c24055d74dad16472ed",
        "commit": "b47bbbe8ca7bc582c96251fa30d86e55de363f68",
        "ref": "xlnx_2026.1.0", "ref_type": "tag",
    },
}
TARGETS = {
    "zynq": {"arch": "arm", "defconfig": "zynq_xcomm_adv7511_defconfig",
             "image": "zImage", "output": "uImage", "triple": "arm-linux-gnueabi",
             "toolchain_sha256": "381d1e1eff13f04fadab3b175098d9d868aa6caf9016a0161a4384e89c7495af"},
    "zynqmp": {"arch": "arm64", "defconfig": "adi_zynqmp_defconfig",
               "image": "Image", "output": "Image", "triple": "aarch64-linux",
               "toolchain_sha256": "0aebb71e8ab23738e21bbceb48ac7f72976b84c9619a9e1309c3eabd44451ba9"},
}


def digest(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def provenance(name, release="2023_R2"):
    target = TARGETS[name]
    return {"release": release, "source": RELEASES[release], "toolchain": {
        "url": BASE + f"x86_64-gcc-12.2.0-nolibc-{target['triple']}.tar.xz",
        "sha256": target["toolchain_sha256"], "version": "12.2.0",
        "cross_compile": target["triple"] + "-"},
        "arch": target["arch"], "defconfig": target["defconfig"],
        "packaging": {"format": target["output"],
                      "load_address": 32768 if name == "zynq" else None,
                      "entry_address": 32768 if name == "zynq" else None},
        "builder_sha256": digest(__file__)}


@contextlib.contextmanager
def lock(path):
    with open(path, "a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def download(spec, cache):
    """Rehash every reuse; never publish partial or rejected downloads."""
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / spec["sha256"]
    with lock(cache / (spec["sha256"] + ".lock")):
        if path.exists():
            if not path.is_symlink() and digest(path) == spec["sha256"]:
                return path
            raise ValueError(f"Corrupt download cache: {path}; remove it explicitly")
        fd, temporary = tempfile.mkstemp(dir=cache, prefix=".download-")
        try:
            with os.fdopen(fd, "wb") as output, urllib.request.urlopen(spec["url"], timeout=120) as response:
                shutil.copyfileobj(response, output)
            if digest(temporary) != spec["sha256"]:
                raise ValueError("Download checksum mismatch: " + spec["url"])
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return path


def extract(archive, destination):
    """Use Python's data filter: reject traversal, special files, escaping links."""
    with tarfile.open(archive) as tar:
        tar.extractall(destination, filter="data")


def uimage(payload, release="2023_R2"):
    """U-Boot legacy Linux/ARM/kernel/uncompressed header, deterministic time."""
    fields = (0x27051956, 0, 0, len(payload), 0x8000, 0x8000,
              zlib.crc32(payload), 5, 2, 2, 0, ("ADI Linux " + release).encode("ascii"))
    header = struct.pack(">7I4B32s", *fields)
    return header[:4] + struct.pack(">I", zlib.crc32(header)) + header[8:] + payload


def validate_image(path, name):
    data = path.read_bytes()
    if name == "zynqmp":
        if len(data) < 64 or data[56:60] != b"ARM\x64":
            raise ValueError("Invalid ARM64 Image")
    else:
        if len(data) < 64:
            raise ValueError("Truncated uImage")
        h = struct.unpack(">7I4B32s", data[:64])
        if (h[0], h[3], h[4], h[5], h[7:11]) != (0x27051956, len(data)-64, 0x8000, 0x8000, (5, 2, 2, 0)):
            raise ValueError("Invalid uImage header")
        if h[1] != zlib.crc32(data[:4] + bytes(4) + data[8:64]) or h[6] != zlib.crc32(data[64:]):
            raise ValueError("Invalid uImage CRC")
        if len(data) < 112 or data[100:104] != b"\x18\x28\x6f\x01":
            raise ValueError("Invalid ARM zImage payload")


def validate_manifest(path, name, release="2023_R2"):
    data = json.loads(path.read_text())
    if data["schema_version"] != 1 or data["platform"] != name or data["provenance"] != provenance(name, release):
        raise ValueError("Artifact provenance mismatch")
    image = Path(data["kernel_image"])
    # Manifest may reference only a generation immediately below its directory.
    if not image.is_absolute() or image.is_symlink() or image.resolve().parent.parent != path.parent.resolve():
        raise ValueError("Unsafe artifact path")
    if image.name != TARGETS[name]["output"] or digest(image) != data["sha256"]:
        raise ValueError("Artifact checksum mismatch")
    validate_image(image, name)
    return data


def run(command, env):
    print("+ " + " ".join(map(str, command)), file=sys.stderr, flush=True)
    subprocess.run(list(map(str, command)), check=True, env=env, stdout=sys.stderr)


def build(name, output, cache, jobs, force=False, release="2023_R2"):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "artifacts.json"
    with lock(output / ".build.lock"):
        if manifest.exists() and not force:
            validate_manifest(manifest, name, release)
            return manifest
        spec = provenance(name, release)
        source_tar = download(spec["source"], cache)
        tools_tar = download(spec["toolchain"], cache)
        # Never trust a mutable extracted source/toolchain cache. Extract verified
        # archives into a new private directory on every actual build.
        with tempfile.TemporaryDirectory(prefix=".build-", dir=output) as temporary:
            work = Path(temporary)
            extract(source_tar, work / "source")
            extract(tools_tar, work / "tools")
            source = work / "source" / ("linux-" + spec["source"]["commit"])
            compilers = list((work / "tools").rglob(spec["toolchain"]["cross_compile"] + "gcc"))
            if len(compilers) != 1:
                raise ValueError("Toolchain compiler missing or ambiguous")
            cross = str(compilers[0])[:-3]
            env = {key: value for key, value in os.environ.items()
                   if key in ("HOME", "PATH", "TMPDIR")}
            env.update(LC_ALL="C", KBUILD_BUILD_USER="cim", KBUILD_BUILD_HOST="cim",
                       KBUILD_BUILD_TIMESTAMP="Thu Jan 1 00:00:00 UTC 1970",
                       KBUILD_BUILD_VERSION="1", SOURCE_DATE_EPOCH="0")
            target = TARGETS[name]
            command = ["make", "-C", source, f"O={work / 'build'}", f"ARCH={target['arch']}", f"CROSS_COMPILE={cross}"]
            run(command + [target["defconfig"]], env)
            run(command + [f"-j{jobs}", target["image"]], env)
            payload = (work / "build" / "arch" / target["arch"] / "boot" / target["image"]).read_bytes()
            staged = work / target["output"]
            staged.write_bytes(uimage(payload, release) if name == "zynq" else payload)
            validate_image(staged, name)
            # Immutable generations keep existing readers valid during rebuild.
            generation = Path(tempfile.mkdtemp(prefix="image-", dir=output))
            image = generation / target["output"]
            os.replace(staged, image)
            data = {"schema_version": 1, "platform": name,
                    "kernel_image": str(image), "sha256": digest(image), "provenance": spec}
            staged_manifest = work / "artifacts.json"
            staged_manifest.write_text(json.dumps(data, indent=2) + "\n")
            os.replace(staged_manifest, manifest)
        validate_manifest(manifest, name, release)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True, choices=TARGETS)
    parser.add_argument("--release", choices=RELEASES, default="2023_R2")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path.home() / ".cache/cim/adi-linux")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--force", action="store_true", help="Rebuild; leave old artifacts intact on failure")
    parser.add_argument("--verify", action="store_true", help="Offline validation only; no download/build")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if args.verify:
        validate_manifest(args.output.resolve() / "artifacts.json", args.platform, args.release)
        print(args.output.resolve() / "artifacts.json")
        return
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        parser.error("Pinned toolchains require Linux x86_64")
    print(build(args.platform, args.output, args.cache.resolve(), args.jobs, args.force, args.release))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError, tarfile.TarError) as error:
        sys.exit(f"kernel build failed: {error}")
