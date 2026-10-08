# `adi-linux` — ADI Linux kernel (selectable release and platform)

Self-contained, kernel-only target that builds `analogdevicesinc/linux` images
for Zynq and ZynqMP from checksum-pinned source and toolchain archives. The
release and platform are selected at make time in a single initialized
workspace. It does **not** build DTBs, install modules, build a root filesystem
or BOOT.BIN, flash, reserve or test boards; device-tree overlays are maintained
separately. Upstream defconfigs and their embedded firmware selections are
preserved without pruning.

| File | Purpose |
|---|---|
| `sdk.yml` | Manifest: variables, `copy_files`, `sdk-build` recipe |
| `os-dependencies.yml` | Host packages (Ubuntu 24.04 recipe) |
| `build-kernel.py` | Pinned downloader/builder/verifier; copied to `scripts/build-kernel.py` |
| `guide-linux.py` | Offline discovery and guided wizard; copied to `scripts/guide-linux.py` |
| `linux.mk` | `make guide`, `make list-combos`, `make list-dts`, … helper targets |
| `boot_pairings_2026_r1.csv` | Devicetree ↔ HDL project map for the 2026_R1 Kuiper release; copied to `scripts/` |

## Requirements

Linux x86_64 host, Python 3.11.8+ (tarfile data-extraction filter), GNU make,
host GCC, `bc`, `bison`, `flex`, `libssl-dev`, `libelf-dev`. Allow several GB
of working space and an initial network download of source and toolchains.
No root privileges are required after host dependencies are installed
(`cim install os-deps --yes` in the workspace may need sudo).

## Build with cim

```bash
cim init --target adi-linux --source https://github.com/tfcollins/datax-manifests.git \
  --workspace "$HOME/cim-linux" --yes
cd "$HOME/cim-linux"
cim makefile
make sdk-build KERNEL_JOBS=4
python3 scripts/build-kernel.py --platform zynq --output artifacts/2023_R2/zynq --verify
```

Pin to a reviewed commit of this repository with `--version <commit>` for
immutable initialization, or use `--source /absolute/path/to/datax-manifests`
for local development.

Defaults are `KERNEL_RELEASE=2023_R2`, `KERNEL_PLATFORM=zynq`, `KERNEL_JOBS=4`.
Select either release (`2023_R2`, `2026_R1`) and platform (`zynq`, `zynqmp`)
in the same workspace:

```bash
make sdk-build KERNEL_RELEASE=2026_R1 KERNEL_PLATFORM=zynqmp
```

`KERNEL_OUTPUT` defaults to `artifacts/$(KERNEL_RELEASE)/$(KERNEL_PLATFORM)`
and is resolved by make, so overriding one selector never reuses the other
pair's output. An explicit `KERNEL_OUTPUT=/path` is an exact override — keep
custom paths separate per release/platform. Use `KERNEL_JOBS` rather than an
outer `make -j` to control kernel parallelism. Initialization alone does not
compile Linux.

### Supported combinations

| KERNEL_RELEASE | KERNEL_PLATFORM | Default KERNEL_OUTPUT | Image |
|---|---|---|---|
| 2023_R2 | zynq | artifacts/2023_R2/zynq | uImage |
| 2023_R2 | zynqmp | artifacts/2023_R2/zynqmp | Image |
| 2026_R1 | zynq | artifacts/2026_R1/zynq | uImage |
| 2026_R1 | zynqmp | artifacts/2026_R1/zynqmp | Image |

The final image is in a generation subdirectory of the output; `artifacts.json`
at the output root is the only discovery interface.

These executable examples preview every supported selection without downloads
or artifact changes (`tests/test_linux_docs.py` runs this exact block):

<!-- linux-offline-examples -->
```bash
python3 scripts/guide-linux.py --list
python3 scripts/guide-linux.py --dry-run --release 2023_R2 --platform zynq --jobs 4
python3 scripts/guide-linux.py --dry-run --release 2023_R2 --platform zynqmp --jobs 4
python3 scripts/guide-linux.py --dry-run --release 2026_R1 --platform zynq --jobs 4
python3 scripts/guide-linux.py --dry-run --release 2026_R1 --platform zynqmp --jobs 4
```

## Devicetree

A flattened devicetree can be built with the kernel from the same pinned
source tree. `KERNEL_DTS` names the `.dts` (without extension) as it appears
under `arch/<arch>/boot/dts[/xilinx]` in the kernel; `auto` looks it up from
`HDL_PROJECT` in `boot_pairings_<release>.csv`, the per-project map ADI
publishes with each Kuiper release:

```bash
make list-dts                                   # every zynq/zynqmp devicetree in the CSV
make list-dts HDL_PROJECT=fmcomms2_zcu102       # the ones for one HDL project
make sdk-build KERNEL_RELEASE=2026_R1 KERNEL_PLATFORM=zynqmp KERNEL_DTS=zynqmp-jupiter-sdr
make sdk-build KERNEL_RELEASE=2026_R1 KERNEL_PLATFORM=zynq   HDL_PROJECT=adv7511_zed KERNEL_DTS=auto
```

`KERNEL_DTS` is the primary selector; `HDL_PROJECT` is a lookup helper, because
the map is many-to-many — `fmcomms2_zcu102` serves both the fmcomms2-3 and
fmcomms4 devicetrees, so `auto` fails with the candidates when a project has
more than one and you pick explicitly. A DTS that is not in the CSV is still
built if the kernel tree has it; the CSV is a convenience, not a gate. Rows
for Versal, MicroBlaze and Intel SoC designs are listed but cannot be built
here (`adi-linux` is Zynq / ZynqMP only). Only the 2026_R1 CSV exists; other
releases fall back to it with a note.

With a devicetree selected the artifacts land in
`<KERNEL_OUTPUT>/<dts>/` — `artifacts/2026_R1/zynqmp/zynqmp-jupiter-sdr/` by
default — so several devicetrees for one platform never share a manifest.
The blob is named the way Kuiper expects it on the boot partition
(`devicetree.dtb` for Zynq, `system.dtb` for ZynqMP) and `artifacts.json`
gains:

```json
"devicetree": {"dts": "zynqmp-jupiter-sdr", "path": "/abs/.../image-xxxx/system.dtb", "sha256": "..."}
```

To iterate on a devicetree without rebuilding the kernel, or to compile every
CSV devicetree for a platform in one go (seconds, not minutes):

```bash
make dtb KERNEL_PLATFORM=zynqmp KERNEL_DTS=zynqmp-jupiter-sdr      # -> artifacts/.../zynqmp-jupiter-sdr/system.dtb
make dtb KERNEL_PLATFORM=zynq KERNEL_DTS=all                        # every zynq row of the CSV
python3 scripts/build-kernel.py --dtb-only --platform zynqmp --dts a,b,c --output dtbs
```

`--dtb-only` extracts the pinned source and toolchain, applies the platform
defconfig and builds just the `.dtb` targets; results go to
`<output>/<dts>/<devicetree.dtb|system.dtb>` with no `artifacts.json`.
`tests/test_adi_devicetree.py` uses it to compile all 67 zynq and 49 zynqmp
devicetrees of the CSV from the 2026_R1 tree (and a representative set from
2023_R2) — run with `CIM_NETWORK=1`; CI does this on every push.

`--verify` (and a cached rebuild) checks the devicetree hash and header too,
and a kernel-only manifest does not satisfy a request with `KERNEL_DTS` set.
The CSV's `HDL_Location` column names the matching bitstream directory on the
Kuiper SD card; that side is produced by the [`hdl`](../hdl/README.md) target.

## Guided build (like the HDL target)

After `cim makefile`:

```bash
make guide-help
make list-combos
make guide          # interactive wizard
make guide-dry-run  # wizard that stops before confirmation
```

The wizard selects release, platform, devicetree (from the CSV, or none), job
count and output folder, then prints
shell-quoted build and offline verification commands. Enter accepts a default;
`?` or `list` shows choices; at the final prompt explicitly choose `build` or
`verify` — the default is **no**. `q`, `cancel`, `quit`, Ctrl-C or EOF exit
without starting anything. Release `2026_R1` selects tag `xlnx_2026.1.0`.

Direct, non-interactive use needs an explicit action:

```bash
python3 scripts/guide-linux.py --verify --release 2026_R1 --platform zynqmp --output artifacts/2026_R1/zynqmp
python3 scripts/guide-linux.py --build  --release 2023_R2 --platform zynq --jobs 4
```

Options: `-i/--interactive`, `-l/--list`, `--release`, `--platform`, `--dts`,
`--hdl-project`, `-j/--jobs`, `--output`, at most one of `--dry-run | --build | --verify`,
`-h/--help`. The guide passes arguments directly (no shell); paths with spaces
are preserved, but upstream kernel make does not support spaces in a fresh
build — choose a space-free output path. The guide never changes
`make sdk-build` defaults and does not expose the helper's `--cache`/`--force`.

## Standalone helper CLI

The same implementation is callable directly from this repository:

```bash
python3 targets/adi-linux/build-kernel.py --release 2026_R1 --platform zynq \
  --output /absolute/output/2026_R1/zynq --jobs 4
```

`--platform` and `--output` are required (`--list-dts [--hdl-project X]`
needs neither); `--dts <name|auto>` adds the devicetree; `--release` defaults to `2023_R2`;
standalone `--jobs` defaults to the host CPU count. Exit zero means the
manifest and image were validated. Stdout contains **only** the absolute
`artifacts.json` path; logs go to stderr. `--verify` validates offline without
downloads or builds. `--cache DIR` selects the archive cache (default
`~/.cache/cim/adi-linux`). `--force` rebuilds without invalidating a previously
published generation on failure. Always pass the same release to `--verify`
that was used to build — never verify a 2026_R1 image with the implicit
2023_R2 default.

## Pins and packaging

* **2023_R2**: `analogdevicesinc/linux` branch `2023_R2` frozen at commit
  `86d61468a7856e952c7ca237f798d86d6abd2e27` (the lowercase `2023_r2` tag is
  intentionally not substituted).
* **2026_R1**: tag `xlnx_2026.1.0`, commit
  `b47bbbe8ca7bc582c96251fa30d86e55de363f68`, archive SHA-256
  `0886274c27356de24e3b7030817e1669d1e14b42a17a2c24055d74dad16472ed`,
  kernel 6.12.77. Its `firmware/` tree carries the complete
  `CONFIG_EXTRA_FIRMWARE` selections (24 files ARM, 38 files ARM64, including
  Navassa and ADRV9025 files); nothing is pruned or fetched unpinned.
* Compiler: kernel.org x86_64 GCC 12.2.0 nolibc cross-toolchains, SHA-256
  pinned from the vendor `sha256sums.asc`. Prefixes `arm-linux-gnueabi-` and
  `aarch64-linux-` (kernel-only compilers, deliberately not the userspace
  `-gnueabihf`/`-gnu` distro prefixes). Host cross-compilers are never used.
* Zynq: `ARCH=arm`, `zynq_xcomm_adv7511_defconfig`, `zImage` wrapped as a
  legacy `uImage` with load and entry `0x8000`; the stdlib packager writes the
  64-byte U-Boot header (`mkimage` is not a dependency).
* ZynqMP: `ARCH=arm64`, `adi_zynqmp_defconfig`, raw `Image`.

Each build extracts verified archives into a private staging directory and
uses `make O=<separate-build-directory>` with fixed build identity/timestamp
variables; bit-for-bit reproducibility across host utility versions is not
claimed.

## Artifact contract v1

`OUTPUT/artifacts.json` is the only discovery interface — never search build
directories or guess image names.

```json
{
  "schema_version": 1,
  "platform": "zynq",
  "kernel_image": "/absolute/output/zynq/image-<generation>/uImage",
  "sha256": "<64 lowercase hex>",
  "provenance": {
    "release": "2023_R2",
    "source":    {"url": "...", "sha256": "...", "commit": "86d6146...", "ref": "2023_R2"},
    "toolchain": {"url": "...", "sha256": "...", "version": "12.2.0", "cross_compile": "arm-linux-gnueabi-"},
    "arch": "arm",
    "defconfig": "zynq_xcomm_adv7511_defconfig",
    "packaging": {"format": "uImage", "load_address": 32768, "entry_address": 32768},
    "builder_sha256": "<helper file checksum>"
  }
}
```

For ZynqMP: `platform: zynqmp`, format `Image`, `arch: arm64`,
`adi_zynqmp_defconfig`, `aarch64-linux-`, both addresses `null`. SHA-256 always
covers the final packaged image. Image paths are local to the build host;
consumers transferring artifacts must copy the image and set their own path.

## Cache and concurrency

Archives are content-addressed and rehashed on every reuse; a corrupt entry
fails closed — remove the named archive to retry. Downloads are renamed into
place only after checksum verification and extracted with Python's safe data
filter; extracted trees are never cached. Use a private cache/output directory
(checksums are integrity checks, not authentication). A per-output flock
serializes builds and a per-archive flock serializes downloads. Completed
images get new generation directories; a single atomic rename publishes the
manifest after validation, so old generations stay valid for existing readers,
including during `--force` rebuilds. There is no garbage collection. Do not
rely on these locks on filesystems without POSIX flock/rename semantics.

## Using artifacts with pyadi-dt

Build and strictly verify both platforms without a board:

```bash
set -e
for platform in zynq zynqmp; do
  make sdk-build KERNEL_RELEASE=2026_R1 KERNEL_PLATFORM="$platform" KERNEL_JOBS=4
  python3 scripts/build-kernel.py --release 2026_R1 --platform "$platform" \
    --output "artifacts/2026_R1/$platform" --verify
done
```

pyadi-dt spells the 2026 release differently:

| pyadi-dt `ADIDT_CIM_RELEASE` | `KERNEL_RELEASE` / `--release` | Linux source |
|---|---|---|
| `2023_R2` (default) | `2023_R2` | branch 2023_R2, frozen commit |
| `2026-R1` | `2026_R1` | tag xlnx_2026.1.0, frozen commit |

Then export from the same workspace, only for the platforms actually built:

```bash
export ADIDT_CIM_RELEASE=2026-R1
export ADIDT_KERNEL_ARTIFACTS_ZYNQ="$PWD/artifacts/2026_R1/zynq/artifacts.json"
export ADIDT_KERNEL_ARTIFACTS_ZYNQMP="$PWD/artifacts/2026_R1/zynqmp/artifacts.json"
```

The consumer reads the manifest (schema, platform, local image, checksum,
source provenance) and fails on a wrong release rather than falling back.
pyadi-dt's `.github/scripts/prepare_cim_kernel.py` automates
init → build → export; see its
[hardware CI guide](https://github.com/analogdevicesinc/pyadi-dt/blob/main/doc/source/developer/hardware_ci.rst).

## Verification

Fast offline tests (no network, no cross-compiler):

```bash
CIM_BIN=/path/to/cim python3 -m unittest discover -s tests -v
```

With cim available the tests also generate a real workspace Makefile and check
all four release/platform overrides, default isolation and custom output;
without it that case is skipped. Fixture tests prove contracts, not
cross-compilation; a validated real build proves artifact production, not
board boot or hardware qualification.
