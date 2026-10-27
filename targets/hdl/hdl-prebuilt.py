#!/usr/bin/env python3
"""Prebuilt HDL bitstream and boot artifact manager for Analog Devices manifests.

Downloads, caches, verifies, indexes, and unpacks prebuilt FPGA bitstreams,
XSAs, device tree blobs, and BOOT.BIN files from ADI Kuiper Linux boot .deb
packages.
"""

import argparse
import contextlib
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import urllib.request

DEFAULT_CACHE = Path.home() / ".cache" / "cim" / "hdl-boot-debs"

CATALOG = {
    "versal": {
        "url": "https://dl.cloudsmith.io/public/adi/kuiper/deb/debian/pool/trixie/main/a/ad/adi-versal-boot_2026.1.0-1/adi-versal-boot_2026.1.0-1_arm64.deb",
        "md5": "5bee04152cd29a66bff65a1ca6d52d72",
        "sha256": "5d1f74b0d76b1bf6cc92c545ff67df09bd0a37355486e04d1554bd719ff50df5",
        "filename": "adi-versal-boot_2026.1.0-1_arm64.deb",
        "json_member": "boot/versal-common/kuiper_versal.json",
    },
    "zynq": {
        "url": "https://dl.cloudsmith.io/public/adi/kuiper/deb/debian/pool/trixie/main/a/ad/adi-zynq-boot_2026.1.0-1/adi-zynq-boot_2026.1.0-1_armhf.deb",
        "md5": "8c1cc52296bfd1800449a9a67a49432d",
        "sha256": "e686f4daae3c2392b7435848b2df83ad4552c2fb3e144685a45b18f6bfd3e7f9",
        "filename": "adi-zynq-boot_2026.1.0-1_armhf.deb",
        "json_member": "boot/zynq-common/kuiper_zynq.json",
    },
    "zynqmp": {
        "url": "https://dl.cloudsmith.io/public/adi/kuiper/deb/debian/pool/trixie/main/a/ad/adi-zynqmp-boot_2026.1.0-1/adi-zynqmp-boot_2026.1.0-1_arm64.deb",
        "md5": "5324252db27018ee235e939088fedf2f",
        "sha256": "3ecb119c3394c4d7c208e7cfd601b34ad2bc465d085a9cb0c70990c0f2188af0",
        "filename": "adi-zynqmp-boot_2026.1.0-1_arm64.deb",
        "json_member": "boot/zynqmp-common/kuiper_zynqmp.json",
    },
}


class BoundedStream(io.RawIOBase):
    """File-like reader restricted to a fixed byte length with optional seeking."""

    def __init__(self, raw_file, max_bytes):
        self._raw = raw_file
        self._start = raw_file.tell() if hasattr(raw_file, "seekable") and raw_file.seekable() else 0
        self._size = max_bytes
        self._pos = 0

    def readinto(self, b):
        if self._pos >= self._size:
            return 0
        chunk_size = min(len(b), self._size - self._pos)
        chunk = self._raw.read(chunk_size)
        if not chunk:
            return 0
        b[: len(chunk)] = chunk
        self._pos += len(chunk)
        return len(chunk)

    def seek(self, offset, whence=io.SEEK_SET):
        if not (hasattr(self._raw, "seekable") and self._raw.seekable()):
            raise io.UnsupportedOperation("seek")
        if whence == io.SEEK_SET:
            new_pos = offset
        elif whence == io.SEEK_CUR:
            new_pos = self._pos + offset
        elif whence == io.SEEK_END:
            new_pos = self._size + offset
        else:
            raise ValueError(f"Invalid whence: {whence}")
        new_pos = max(0, min(new_pos, self._size))
        self._raw.seek(self._start + new_pos, io.SEEK_SET)
        self._pos = new_pos
        return self._pos

    def tell(self):
        return self._pos

    def seekable(self):
        return hasattr(self._raw, "seekable") and self._raw.seekable()

    def readable(self):
        return True


@contextlib.contextmanager
def file_lock(lock_path):
    """Advisory flock for atomic caching across multiple processes."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def calculate_digest(path_or_stream, algo="sha256"):
    """Compute hex digest of a file or stream."""
    h = hashlib.new(algo)
    if isinstance(path_or_stream, (str, Path)):
        with open(path_or_stream, "rb") as f:
            while chunk := f.read(1024 * 1024):
                h.update(chunk)
    else:
        while chunk := path_or_stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def verify_file(file_path, spec):
    """Check both sha256 and md5 if specified in spec."""
    if not file_path.exists():
        return False
    if "sha256" in spec and spec["sha256"]:
        if calculate_digest(file_path, "sha256") != spec["sha256"]:
            return False
    if "md5" in spec and spec["md5"]:
        if calculate_digest(file_path, "md5") != spec["md5"]:
            return False
    return True


def download_package(arch, cache_dir=DEFAULT_CACHE, force=False):
    """Download and cache deb package for the given architecture."""
    if arch not in CATALOG:
        raise ValueError(f"Unknown architecture '{arch}'. Available: {', '.join(CATALOG)}")
    spec = CATALOG[arch]
    cache_dir = Path(cache_dir).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    target_path = cache_dir / spec["filename"]
    lock_path = cache_dir / (spec["filename"] + ".lock")

    with file_lock(lock_path):
        if not force and verify_file(target_path, spec):
            return target_path

        print(f"Downloading prebuilt package for {arch} from {spec['url']}...", file=sys.stderr)
        fd, temp_path = tempfile.mkstemp(dir=cache_dir, prefix=f".{spec['filename']}-")
        try:
            with os.fdopen(fd, "wb") as out_file:
                with urllib.request.urlopen(spec["url"], timeout=180) as response:
                    shutil.copyfileobj(response, out_file)
            temp_path_obj = Path(temp_path)
            if not verify_file(temp_path_obj, spec):
                raise ValueError(f"Downloaded file checksum mismatch for {spec['url']}")
            os.replace(temp_path, target_path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    return target_path


def open_deb_data_tar(deb_path_or_stream):
    """Generator reading members of data.tar.gz inside a Debian package."""
    if isinstance(deb_path_or_stream, (str, Path)):
        f = open(deb_path_or_stream, "rb")
        should_close = True
    else:
        f = deb_path_or_stream
        should_close = False

    try:
        magic = f.read(8)
        if magic != b"!<arch>\n":
            raise ValueError(f"Not a valid Debian/ar archive: {deb_path_or_stream}")
        while True:
            hdr = f.read(60)
            if len(hdr) < 60:
                break
            name = hdr[:16].decode("latin1").strip().rstrip("/")
            size = int(hdr[48:58].decode("latin1").strip())
            if name.startswith("data.tar"):
                stream = BoundedStream(f, size)
                with tarfile.open(fileobj=stream, mode="r:*") as tar:
                    yield tar
                break
            else:
                f.seek(size + (size % 2), io.SEEK_CUR)
    finally:
        if should_close:
            f.close()


def stream_kuiper_json_from_url(url, json_member_name):
    """Stream just the kuiper json index from remote deb using standard HTTP streaming."""
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        magic = resp.read(8)
        if magic != b"!<arch>\n":
            raise ValueError(f"Remote file is not an ar archive: {url}")
        while True:
            hdr = resp.read(60)
            if len(hdr) < 60:
                break
            name = hdr[:16].decode("latin1").strip().rstrip("/")
            size = int(hdr[48:58].decode("latin1").strip())
            if name.startswith("data.tar"):
                stream = gzip.GzipFile(fileobj=resp)
                tar = tarfile.TarFile(fileobj=stream)
                for m in tar:
                    norm = m.name.lstrip("./")
                    if norm == json_member_name or norm.endswith(Path(json_member_name).name):
                        return json.load(tar.extractfile(m))
                break
            else:
                resp.read(size + (size % 2))
    raise RuntimeError(f"Could not locate {json_member_name} in remote deb {url}")


def get_metadata(arch, cache_dir=DEFAULT_CACHE):
    """Retrieve Kuiper metadata dictionary for an architecture (cached when possible)."""
    if arch not in CATALOG:
        raise ValueError(f"Unknown architecture '{arch}'")
    spec = CATALOG[arch]
    cache_dir = Path(cache_dir).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_json = cache_dir / f"kuiper_{arch}.json"
    deb_path = cache_dir / spec["filename"]

    # 1. Use cached JSON file if present and valid
    if cached_json.exists():
        try:
            with open(cached_json, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # 2. Extract from local deb file if already downloaded
    if deb_path.exists() and verify_file(deb_path, spec):
        for tar in open_deb_data_tar(deb_path):
            for m in tar.getmembers():
                norm = m.name.lstrip("./")
                if norm == spec["json_member"] or norm.endswith(Path(spec["json_member"]).name):
                    data = json.load(tar.extractfile(m))
                    with open(cached_json, "w", encoding="utf-8") as out:
                        json.dump(data, out, indent=2)
                    return data

    # 3. Stream from remote URL if deb not yet downloaded
    data = stream_kuiper_json_from_url(spec["url"], spec["json_member"])
    with open(cached_json, "w", encoding="utf-8") as out:
        json.dump(data, out, indent=2)
    return data


def normalize_token(s):
    """Normalize project/carrier strings for comparison."""
    if not s:
        return ""
    return s.strip().lower().replace("-", "").replace("_", "")


def match_project(projects, target_project, target_board=None):
    """Find matching project entry in Kuiper JSON projects list."""
    proj_norm = normalize_token(target_project)
    board_norm = normalize_token(target_board) if target_board else ""

    candidates = []
    for p in projects:
        p_name = normalize_token(p.get("name", ""))
        p_board = normalize_token(p.get("board", ""))

        # Exact match
        if board_norm:
            if p_name == proj_norm and p_board == board_norm:
                return p
        else:
            if p_name == proj_norm:
                return p

        # Check directory path inside files for substring match
        matched_by_path = False
        for f in p.get("files", []):
            path = normalize_token(f.get("path", ""))
            if board_norm and board_norm in path and proj_norm in path:
                matched_by_path = True
                break
            elif not board_norm and proj_norm in path:
                matched_by_path = True
                break

        if board_norm:
            if (p_name == proj_norm or p_name.startswith(proj_norm) or proj_norm in p_name) and (
                p_board == board_norm or board_norm in p_board
            ):
                candidates.append((1 if p_name == proj_norm else 2, p))
            elif matched_by_path:
                candidates.append((3, p))
        else:
            if p_name == proj_norm or p_name.startswith(proj_norm):
                candidates.append((1 if p_name == proj_norm else 2, p))
            elif matched_by_path:
                candidates.append((3, p))

    if candidates:
        candidates.sort(key=lambda c: c[0])
        return candidates[0][1]

    return None


def find_prebuilt(project, board=None, arch=None, cache_dir=DEFAULT_CACHE):
    """Look up a prebuilt entry across specified or all architectures."""
    archs = [arch] if arch else list(CATALOG.keys())
    for a in archs:
        try:
            meta = get_metadata(a, cache_dir=cache_dir)
            matched = match_project(meta.get("projects", []), project, board)
            if matched:
                return a, matched
        except Exception:
            continue
    return None, None


def extract_prebuilt_files(
    arch, project_entry, output_dir, cache_dir=DEFAULT_CACHE, components="all", project_name=None
):
    """Extract files for the matched project into output_dir."""
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    deb_path = download_package(arch, cache_dir=cache_dir)

    # Determine project directory prefix in the deb archive
    files = project_entry.get("files", [])
    if not files:
        raise ValueError(f"Project entry {project_entry.get('name')} contains no files list")

    first_file = files[0]["path"].lstrip("/")
    proj_dir_rel = Path(first_file).parent
    proj_dir_str = str(proj_dir_rel).replace("\\", "/").rstrip("/") + "/"

    extracted_files = []
    bitstream_found = False

    for tar in open_deb_data_tar(deb_path):
        for member in tar:
            m_path = member.name.lstrip("./")
            if not (m_path == str(proj_dir_rel).replace("\\", "/") or m_path.startswith(proj_dir_str)):
                continue
            if not member.isfile():
                continue
            rel_in_proj = Path(m_path).relative_to(proj_dir_rel)

            if member.name.endswith("bootgen_sysfiles.tgz"):
                # Unpack bootgen_sysfiles.tgz contents (contains system_top.bit/pdi and system_top.xsa)
                tgz_file = tar.extractfile(member)
                if tgz_file:
                    with tarfile.open(fileobj=tgz_file, mode="r:*") as sysfiles_tar:
                        for sub_member in sysfiles_tar:
                            if not sub_member.isfile():
                                continue
                            dest = output_dir / sub_member.name
                            with open(dest, "wb") as out:
                                shutil.copyfileobj(sysfiles_tar.extractfile(sub_member), out)
                            extracted_files.append(str(dest))
                            if sub_member.name in ("system_top.bit", "system_top.pdi"):
                                bitstream_found = True
            elif member.isfile():
                dest = output_dir / rel_in_proj
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as out:
                    shutil.copyfileobj(tar.extractfile(member), out)
                extracted_files.append(str(dest))

    # Also duplicate system_top.xsa into sdk subdirectory if present so build_boot_bin scripts find it
    xsa_path = output_dir / "system_top.xsa"
    if xsa_path.exists():
        names = {project_entry.get("name")}
        if project_name:
            names.add(project_name)
        for name in names:
            if name:
                sdk_dir = output_dir / f"{name}.sdk"
                sdk_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(xsa_path, sdk_dir / "system_top.xsa")

    return extracted_files


def list_prebuilts(arch=None, cache_dir=DEFAULT_CACHE, as_json=False):
    """Print all available prebuilt project / carrier board combinations."""
    archs = [arch] if arch else list(CATALOG.keys())
    if as_json:
        results = []
        for a in archs:
            meta = get_metadata(a, cache_dir=cache_dir)
            for p in meta.get("projects", []):
                results.append({
                    "arch": a,
                    "board": None if p.get("board") == "-" else p.get("board"),
                    "name": p.get("name", ""),
                })
        print(json.dumps(results, indent=2))
        return
    print(f"{'ARCHITECTURE':<14} | {'CARRIER BOARD':<20} | {'PROJECT NAME':<32}")
    print("-" * 15 + "+" + "-" * 22 + "+" + "-" * 34)
    total = 0
    for a in archs:
        meta = get_metadata(a, cache_dir=cache_dir)
        for p in meta.get("projects", []):
            board = p.get("board", "-")
            name = p.get("name", "")
            print(f"{a:<14} | {board:<20} | {name:<32}")
            total += 1
    print("-" * 15 + "+" + "-" * 22 + "+" + "-" * 34)
    print(f"Total: {total} prebuilt configurations available.")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Analog Devices Prebuilt HDL Bitstream & Boot Artifact Manager",
        epilog="Downloads, verifies, indexes and unpacks prebuilt bitstreams and boot files.",
    )
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="deb cache directory")
    parser.add_argument("--arch", choices=list(CATALOG.keys()), help="FPGA architecture")
    parser.add_argument("--project", help="HDL project name (e.g. fmcomms2, jupiter_sdr, ad9081)")
    parser.add_argument("--board", help="Carrier board name (e.g. zcu102, zed)")
    parser.add_argument("--project-name", help="HDL internal project name (e.g. fmcomms2_zcu102)")
    parser.add_argument("--output", type=Path, help="Directory to extract files into")
    parser.add_argument(
        "--components",
        choices=["all", "bitstream", "bootbin", "xsa"],
        default="all",
        help="Components to extract (default: all)",
    )
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    action = parser.add_mutually_exclusive_group()
    action.add_argument("-l", "--list", action="store_true", help="List available prebuilt project combinations")
    action.add_argument("-c", "--check", action="store_true", help="Check if a prebuilt exists for project/board")
    action.add_argument("-x", "--extract", action="store_true", help="Download and extract prebuilt files")
    action.add_argument("-d", "--download", action="store_true", help="Download and cache deb package(s)")

    args = parser.parse_args(argv)

    if args.list:
        list_prebuilts(arch=args.arch, cache_dir=args.cache, as_json=args.json)
        return 0

    if args.check:
        if not args.project:
            parser.error("--check requires --project")
        arch, matched = find_prebuilt(args.project, args.board, arch=args.arch, cache_dir=args.cache)
        if matched:
            if args.json:
                print(json.dumps({
                    "found": True,
                    "arch": arch,
                    "board": matched.get("board"),
                    "name": matched.get("name"),
                }, indent=2))
            else:
                print(f"FOUND: arch={arch} board={matched.get('board')} name={matched.get('name')}")
            return 0
        else:
            if args.json:
                print(json.dumps({
                    "found": False,
                    "project": args.project,
                    "board": args.board or "-",
                }, indent=2))
            else:
                print(f"NOT FOUND: project={args.project} board={args.board or '-'}", file=sys.stderr)
            return 1

    if args.download:
        archs = [args.arch] if args.arch else list(CATALOG.keys())
        for a in archs:
            path = download_package(a, cache_dir=args.cache)
            print(f"Cached {a}: {path}")
        return 0

    if args.extract:
        if not args.project:
            parser.error("--extract requires --project")
        if not args.output:
            parser.error("--extract requires --output")
        arch, matched = find_prebuilt(args.project, args.board, arch=args.arch, cache_dir=args.cache)
        if not matched:
            print(f"Error: No prebuilt design found for {args.project} (board={args.board or '-'})", file=sys.stderr)
            return 1
        print(f"Extracting prebuilts for {args.project}/{args.board or '-'} [{arch}] -> {args.output}...")
        extracted = extract_prebuilt_files(
            arch,
            matched,
            args.output,
            cache_dir=args.cache,
            components=args.components,
            project_name=args.project_name,
        )
        print(f"Extracted {len(extracted)} files:")
        for f in extracted:
            print(f"  {f}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
