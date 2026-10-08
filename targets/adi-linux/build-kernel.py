#!/usr/bin/env python3
"""Pinned ADI kernel builder. Linux x86_64, Python >= 3.11 (stdlib only)."""
import argparse
import contextlib
import csv
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
# Kuiper SD-card names for the flattened devicetree of each platform.
DTB_NAME = {"zynq": "devicetree.dtb", "zynqmp": "system.dtb"}
# FPGA_Type column of the boot-pairings CSV -> adi-linux platform (others are
# listed but cannot be built by this helper).
PAIRING_PLATFORM = {"zynq": "zynq", "zynqu": "zynqmp"}
DTB_MAGIC = b"\xd0\x0d\xfe\xed"


def pairings_path(release):
    """boot_pairings_<release>.csv next to this script, falling back to the newest."""
    here = Path(__file__).resolve().parent
    exact = here / f"boot_pairings_{release.lower()}.csv"
    if exact.exists():
        return exact, False
    candidates = sorted(here.glob("boot_pairings_*.csv"))
    if not candidates:
        raise ValueError("No boot_pairings_*.csv next to " + str(here))
    return candidates[-1], True


def load_pairings(release):
    """Rows of the DTS <-> HDL project map, each with a 'platform' (or None)."""
    path, fallback = pairings_path(release)
    rows = []
    with open(path, newline="") as stream:
        for row in csv.DictReader(stream):
            row = {key.strip(): value.strip() for key, value in row.items() if key}
            row["platform"] = PAIRING_PLATFORM.get(row["FPGA_Type"])
            rows.append(row)
    return rows, path, fallback


def find_dts(rows, hdl_project=None, platform=None, dts=None):
    """Rows matching the HDL project and/or platform (exact DTS wins)."""
    hits = rows
    if dts:
        hits = [r for r in hits if r["DTS"] == dts]
    if hdl_project:
        hits = [r for r in hits if r["HDL_Project"] == hdl_project]
    if platform:
        hits = [r for r in hits if r["platform"] == platform]
    return hits


def resolve_dts(release, platform, dts=None, hdl_project=None):
    """Turn --dts/--hdl-project into one DTS name, or raise with the choices."""
    if dts and dts != "auto":
        return dts
    rows, path, _ = load_pairings(release)
    if not hdl_project:
        raise ValueError("--dts auto needs --hdl-project (or pass --dts <name>)")
    hits = find_dts(rows, hdl_project=hdl_project)
    if not hits:
        raise ValueError(f"No devicetree in {path.name} for HDL project '{hdl_project}'; pass --dts <name>")
    others = sorted({r["platform"] or r["FPGA_Type"] for r in hits if r["platform"] != platform})
    hits = [r for r in hits if r["platform"] == platform]
    if not hits:
        buildable = any(o in TARGETS for o in others)
        raise ValueError(f"HDL project '{hdl_project}' is a {', '.join(others)} design in {path.name}, not {platform}"
                         + (f"; set KERNEL_PLATFORM={others[0]}" if buildable else " (not buildable by adi-linux)"))
    if len(hits) > 1:
        names = ", ".join(r["DTS"] for r in hits)
        raise ValueError(f"HDL project '{hdl_project}' has several devicetrees: {names}; pass --dts <name>")
    return hits[0]["DTS"]


def dts_source(source, arch, dts):
    """Where the .dts lives in this kernel tree: dts/xilinx/ (6.12+) or dts/ root (6.1)."""
    for sub in ("xilinx", ""):
        if (source / "arch" / arch / "boot" / "dts" / sub / (dts + ".dts")).exists():
            return sub
    raise ValueError(f"Devicetree source {dts}.dts not found under arch/{arch}/boot/dts in this kernel")


def validate_dtb(path):
    data = path.read_bytes()
    if len(data) < 40 or data[:4] != DTB_MAGIC or struct.unpack(">I", data[4:8])[0] != len(data):
        raise ValueError("Invalid flattened devicetree blob")


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


def check_generation_path(path, artifact):
    # Manifest may reference only a generation immediately below its directory.
    if not artifact.is_absolute() or artifact.is_symlink() or artifact.resolve().parent.parent != path.parent.resolve():
        raise ValueError("Unsafe artifact path")


def validate_manifest(path, name, release="2023_R2", dts=None):
    data = json.loads(path.read_text())
    if data["schema_version"] != 1 or data["platform"] != name or data["provenance"] != provenance(name, release):
        raise ValueError("Artifact provenance mismatch")
    image = Path(data["kernel_image"])
    check_generation_path(path, image)
    if image.name != TARGETS[name]["output"] or digest(image) != data["sha256"]:
        raise ValueError("Artifact checksum mismatch")
    validate_image(image, name)
    tree = data.get("devicetree")
    if dts and (tree is None or tree.get("dts") != dts):
        raise ValueError(f"Artifacts were built {'without a devicetree' if tree is None else 'for ' + tree.get('dts', '?')}, "
                         f"not {dts}; use a separate --output or --force")
    if tree is not None:
        dtb = Path(tree["path"])
        check_generation_path(path, dtb)
        if dtb.parent != image.parent or dtb.name != DTB_NAME[name] or digest(dtb) != tree["sha256"]:
            raise ValueError("Devicetree checksum mismatch")
        validate_dtb(dtb)
    return data


def run(command, env):
    print("+ " + " ".join(map(str, command)), file=sys.stderr, flush=True)
    subprocess.run(list(map(str, command)), check=True, env=env, stdout=sys.stderr)


@contextlib.contextmanager
def configured_tree(name, release, cache, workdir):
    """Pinned source + toolchain extracted into workdir, defconfig applied.

    Yields (source_dir, make_command, env). Never trusts a mutable extracted
    cache: every call extracts the verified archives afresh.
    """
    spec = provenance(name, release)
    source_tar = download(spec["source"], cache)
    tools_tar = download(spec["toolchain"], cache)
    work = Path(workdir)
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
    yield source, command, env


def build_dtbs(name, release, dts_names, output, cache, jobs):
    """Compile devicetrees only (no kernel image): output/<dts>/<DTB_NAME> each.

    Much cheaper than a kernel build; used to iterate on a devicetree and by
    the test-suite to prove every CSV row compiles.
    """
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    target = TARGETS[name]
    results = {}
    with tempfile.TemporaryDirectory(prefix=".dtb-", dir=output) as temporary, \
            configured_tree(name, release, cache, temporary) as (source, command, env):
        work = Path(temporary)
        targets = {}
        for dts in dts_names:
            sub = dts_source(source, target["arch"], dts)
            targets[dts] = (sub, (sub + "/" if sub else "") + dts + ".dtb")
        run(command + [f"-j{jobs}"] + [t for _, t in targets.values()], env)
        for dts, (sub, _) in targets.items():
            built = work / "build" / "arch" / target["arch"] / "boot" / "dts" / sub / (dts + ".dtb")
            validate_dtb(built)
            dest = output / dts / DTB_NAME[name]
            dest.parent.mkdir(exist_ok=True)
            shutil.copyfile(built, dest)
            results[dts] = dest
    return results


def build(name, output, cache, jobs, force=False, release="2023_R2", dts=None):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "artifacts.json"
    with lock(output / ".build.lock"):
        if manifest.exists() and not force:
            validate_manifest(manifest, name, release, dts)
            return manifest
        spec = provenance(name, release)
        with tempfile.TemporaryDirectory(prefix=".build-", dir=output) as temporary, \
                configured_tree(name, release, cache, temporary) as (source, command, env):
            work = Path(temporary)
            target = TARGETS[name]
            run(command + [f"-j{jobs}", target["image"]], env)
            payload = (work / "build" / "arch" / target["arch"] / "boot" / target["image"]).read_bytes()
            staged = work / target["output"]
            staged.write_bytes(uimage(payload, release) if name == "zynq" else payload)
            validate_image(staged, name)
            staged_dtb = None
            if dts:
                sub = dts_source(source, target["arch"], dts)
                dtb_target = (sub + "/" if sub else "") + dts + ".dtb"
                run(command + [f"-j{jobs}", dtb_target], env)
                staged_dtb = work / DTB_NAME[name]
                shutil.copyfile(work / "build" / "arch" / target["arch"] / "boot" / "dts" / sub / (dts + ".dtb"), staged_dtb)
                validate_dtb(staged_dtb)
            # Immutable generations keep existing readers valid during rebuild.
            generation = Path(tempfile.mkdtemp(prefix="image-", dir=output))
            image = generation / target["output"]
            os.replace(staged, image)
            data = {"schema_version": 1, "platform": name,
                    "kernel_image": str(image), "sha256": digest(image), "provenance": spec}
            if staged_dtb is not None:
                dtb = generation / DTB_NAME[name]
                os.replace(staged_dtb, dtb)
                data["devicetree"] = {"dts": dts, "path": str(dtb), "sha256": digest(dtb)}
            staged_manifest = work / "artifacts.json"
            staged_manifest.write_text(json.dumps(data, indent=2) + "\n")
            os.replace(staged_manifest, manifest)
        validate_manifest(manifest, name, release, dts)
    return manifest


def list_dts(release, platform=None, hdl_project=None):
    rows, path, fallback = load_pairings(release)
    if fallback:
        print(f"note: no boot_pairings_{release.lower()}.csv; using {path.name}", file=sys.stderr)
    hits = find_dts(rows, hdl_project=hdl_project, platform=platform)
    if platform is None and hdl_project is not None:
        hits = find_dts(rows, hdl_project=hdl_project)
    print(f"{'DTS':<70} {'HDL_PROJECT':<48} PLATFORM")
    for row in hits:
        plat = row["platform"] or f"{row['FPGA_Type']} (not buildable here)"
        print(f"{row['DTS']:<70} {row['HDL_Project']:<48} {plat}")
    if not hits:
        print("(no matching rows)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=TARGETS, default="zynq")
    parser.add_argument("--release", choices=RELEASES, default="2023_R2")
    parser.add_argument("--output", type=Path, help="Artifact directory (required unless --list-dts); "
                        "with --dts the artifacts go to OUTPUT/<dts>")
    parser.add_argument("--cache", type=Path, default=Path.home() / ".cache/cim/adi-linux")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--force", action="store_true", help="Rebuild; leave old artifacts intact on failure")
    parser.add_argument("--verify", action="store_true", help="Offline validation only; no download/build")
    parser.add_argument("--dts", default="", help="Devicetree to build alongside the kernel: a DTS name "
                        "from the kernel tree, or 'auto' to look it up from --hdl-project (default: kernel only)")
    parser.add_argument("--hdl-project", default="", help="HDL project (boot_pairings CSV) for --dts auto / --list-dts")
    parser.add_argument("--list-dts", action="store_true", help="List devicetrees from the boot-pairings CSV and exit")
    parser.add_argument("--dtb-only", action="store_true", help="Compile only the devicetree(s) in --dts "
                        "(comma-separated, or 'all' for every CSV row of the platform) to OUTPUT/<dts>/; no kernel")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if args.list_dts:
        list_dts(args.release, None if args.hdl_project else args.platform, args.hdl_project or None)
        return
    if args.output is None:
        parser.error("--output is required")
    if args.dtb_only:
        if not args.dts:
            parser.error("--dtb-only needs --dts <name[,name...]|all>")
        if args.dts == "all":
            rows, _, _ = load_pairings(args.release)
            # several HDL variants can share one devicetree: build each DTS once
            names = list(dict.fromkeys(r["DTS"] for r in find_dts(rows, platform=args.platform)))
        else:
            names = [resolve_dts(args.release, args.platform, n, args.hdl_project or None) for n in args.dts.split(",")]
        if platform.system() != "Linux" or platform.machine() != "x86_64":
            parser.error("Pinned toolchains require Linux x86_64")
        for dest in build_dtbs(args.platform, args.release, names, args.output, args.cache.resolve(), args.jobs).values():
            print(dest)
        return
    dts = resolve_dts(args.release, args.platform, args.dts or None, args.hdl_project or None) if (args.dts or args.hdl_project) else None
    if dts:
        # Devicetree artifacts live one level below the kernel-only layout so
        # several devicetrees for one platform never share a manifest.
        args.output = args.output / dts
    if args.verify:
        validate_manifest(args.output.resolve() / "artifacts.json", args.platform, args.release, dts)
        print(args.output.resolve() / "artifacts.json")
        return
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        parser.error("Pinned toolchains require Linux x86_64")
    print(build(args.platform, args.output, args.cache.resolve(), args.jobs, args.force, args.release, dts))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError, tarfile.TarError) as error:
        sys.exit(f"kernel build failed: {error}")
