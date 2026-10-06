# `hdl` — ADI HDL reference designs (selectable release)

Builds [analogdevicesinc/hdl](https://github.com/analogdevicesinc/hdl)
reference designs with vendor EDA tools (AMD/Xilinx Vivado, Intel Quartus
Prime, Lattice Radiant). One target covers every HDL release: the release is a
make variable, and the matching Vivado version is selected automatically.

| File | Purpose |
|---|---|
| `sdk.yml` | Manifest: variables, `hdl` git, `sdk-build` / `sdk-clean` recipes |
| `os-dependencies.yml` | Host packages |
| `build-hdl.sh` | Release switching, tool detection, matrix inspection, guided wizard; copied to `scripts/build-hdl.sh` |
| `hdl.mk` | `make guide`, `make list-combos`, … helper targets |

`build_boot_bin.sh` is fetched from
[wiki-scripts](https://github.com/analogdevicesinc/wiki-scripts) into
`scripts/` for BOOT.BIN generation.

## Quick start

```bash
cim init --target hdl --source https://github.com/tfcollins/datax-manifests.git --workspace ~/cim-hdl
cd ~/cim-hdl
cim makefile

make check-tools                      # which EDA tools are installed, which Vivado the release wants
make list-combos                      # every project / carrier board / tool for the selected release
make list-boards HDL_PROJECT=ad9081_fmca_ebz
make guide                            # interactive wizard
make sdk-build HDL_PROJECT=fmcomms2 HDL_BOARD=zed BUILD_BOOT_BIN=true
```

## Selecting a release

`HDL_RELEASE` is any branch, tag or commit of `analogdevicesinc/hdl`
(default `hdl_2026_r1`). `cim init` clones the default; `build-hdl.sh` then
switches the workspace `hdl/` checkout to the requested release before every
inspection or build, fetching it from origin (or from GitHub when the origin
is a mirror without it).

```bash
make list-combos HDL_RELEASE=hdl_2023_r2
make sdk-build  HDL_RELEASE=hdl_2023_r2 HDL_PROJECT=fmcomms2 HDL_BOARD=zed
```

| `HDL_RELEASE` | Vivado selected by `VIVADO=auto` |
|---|---|
| `hdl_2023_r2` | 2023.2 |
| `hdl_2026_r1` (default) | 2025.1 |
| `main` | 2025.1 |
| anything else | none — pass `VIVADO=/path/to/Vivado` |

`VIVADO=auto` probes `/opt/Xilinx/<ver>/Vivado`, `/opt/Xilinx/Vivado/<ver>`
and the same under `/tools`; `$XILINX_VIVADO` is honoured if set. Quartus and
Radiant paths come from `QUARTUS` / `LATTICE_RADIANT` (or
`$QUARTUS_ROOTDIR`) and do not depend on the release.

`analogdevicesinc/hdl` keeps documentation images in Git LFS and some objects
are missing upstream; builds never need them. `build-hdl.sh` sets
`GIT_LFS_SKIP_SMUDGE=1` for its own git operations, and if `git-lfs` is
installed on your host run `cim init` with `GIT_LFS_SKIP_SMUDGE=1` too.

Switching release refuses to touch a dirty `hdl/` worktree (tracked
modifications; untracked build output is fine). A local branch of the same
name is used as-is, so your own commits are never reset — run
`git -C hdl pull` to move a release forward.

## Variables

| Variable | Default | Meaning |
|---|---|---|
| `HDL_RELEASE` | `hdl_2026_r1` | Release (branch/tag/sha) of `analogdevicesinc/hdl` |
| `VIVADO` | `auto` | Vivado install dir, or `auto` to derive from the release |
| `QUARTUS` | `/opt/intelFPGA_pro/23.4/quartus` | Quartus install dir |
| `LATTICE_RADIANT` | `/usr/local/radiant` | Radiant install dir |
| `HDL_PROJECT` | `fmcomms2` | Project under `hdl/projects/` |
| `HDL_BOARD` | `zcu102` | Carrier board under the project |
| `MAKE_JOBS` | `-j$(nproc)` | Parallel jobs passed to the project make |
| `DIR_NAME` | `build` | Build output directory name inside the project |
| `BUILD_BOOT_BIN` | `false` | Generate BOOT.BIN after a Zynq / ZynqMP / Versal build |
| `BOOT_BIN_UBOOT` | `download` | `u-boot.elf` path, or `download` ADI's prebuilt |
| `BOOT_BIN_ATF` | `download` | ZynqMP/Versal: `bl31.elf` path, ATF source dir, or `download` (build it) |

## EDA tool matrix

| Vendor tool | Carrier boards (examples) | Default environment |
|---|---|---|
| **AMD/Xilinx Vivado** | `zed`, `zc702`, `zc706`, `zcu102`, `coraz7s`, `k26`, `kv260`, `vck190`, `vmk180`, `vpk180`, `kcu105`, `vcu118`, `ac701`, … | `$VIVADO/settings64.sh` (auto per release) |
| **Intel Quartus Prime** (Pro 23.4 / Standard) | `de10nano`, `c5soc`, `a10soc`, `a10gx`, `s10soc`, `fm87` | `$QUARTUS/bin` on PATH, or `$QUARTUS_ROOTDIR` |
| **Lattice Radiant / Propel** | `lfcpnx` (Certus-NX) | `$LATTICE_RADIANT/bin/lin64` on PATH |

The tool for a project/board is detected from its Makefile
(`project-xilinx.mk` / `project-intel.mk` / `project-lattice.mk`).

### Projects without carrier boards

SOM-style designs (`jupiter_sdr`, `pluto`, `m2k`, `sidekiqz2`, `usrpe31x`, …)
have the vendor Makefile directly in `projects/<name>/` and no carrier
subdirectories. They are built with just the project name — `HDL_BOARD` is
ignored (with a warning, since `sdk.yml` always passes its default):

```bash
make sdk-build HDL_PROJECT=jupiter_sdr
make list-boards HDL_PROJECT=jupiter_sdr     # "has no carrier boards; built directly"
```

`make list-combos` shows these with `-` in the carrier board column. BOOT.BIN
generation uses the Makefile's `PROJECT_NAME` for the `.sdk` path, so it works
for both layouts.

### BOOT.BIN

`BUILD_BOOT_BIN=true` (or the wizard's prompt) is offered for any design whose
device has a boot ROM. The device is read from the project's
`system_project.tcl` (carrier-less designs such as `jupiter_sdr`, `pluto`,
`m2k`) or from the board table in `projects/scripts/adi_project_xilinx.tcl`
(carrier designs), and selects the matching helper from
[wiki-scripts](https://github.com/analogdevicesinc/wiki-scripts) — all three
are fetched into `scripts/` by `cim init`:

| Device | Helper | Inputs |
|---|---|---|
| Zynq-7000 (`xc7z*`) | `build_boot_bin.sh` | XSA, `BOOT_BIN_UBOOT` → FSBL + bit + u-boot |
| Zynq UltraScale+ (`xczu*`) | `build_zynqmp_boot_bin.sh` | XSA, `BOOT_BIN_UBOOT`, `BOOT_BIN_ATF` → FSBL + PMUFW + bit + bl31 + u-boot |
| Versal (`xcv*`) | `build_versal_boot_bin.sh` | XSA, `BOOT_BIN_UBOOT`, `BOOT_BIN_ATF` (+ DTB; see the script) |

Kintex / Virtex / Artix, Intel and Lattice designs are not eligible;
requesting BOOT.BIN for them prints a warning and skips it.

* `BOOT_BIN_UBOOT=download` (default) fetches ADI's prebuilt `u-boot.elf` for
  the carrier detected inside the XSA — the ZynqMP list covers `zcu102`,
  `adrv2crr_*`, `jupiter_sdr`, `k26`; the Zynq-7000 list `zed`, `zc702`,
  `zc706`, `coraz7s`, `ccbob_*`, `ccfmc_*`, `usrpe31x`. Other carriers need an
  explicit `BOOT_BIN_UBOOT=/path/to/u-boot.elf`.
* `BOOT_BIN_ATF=download` (default, ZynqMP/Versal) clones and builds
  arm-trusted-firmware, which needs `aarch64-linux-gnu-gcc`
  (`gcc-aarch64-linux-gnu`, included in `os-dependencies.yml`). Pass a
  prebuilt `BOOT_BIN_ATF=/path/to/bl31.elf` or an ATF source directory to skip
  that.
* The helpers need `xsct`, `bootgen` and `vitis` on PATH — i.e. Vitis, not
  just Vivado, installed alongside the selected version.

```bash
make sdk-build HDL_PROJECT=jupiter_sdr BUILD_BOOT_BIN=true
make sdk-build HDL_PROJECT=fmcomms2 HDL_BOARD=zcu102 BUILD_BOOT_BIN=true BOOT_BIN_ATF=~/bl31.elf
```

Output lands in `hdl/projects/<...>/output_boot_bin/BOOT.BIN`.

To build u-boot and BL31 from source instead of downloading ADI's prebuilt
blobs, use the [`hdl-boot`](../hdl-boot/README.md) target (same workspace,
`extends: hdl`), or build them separately with
[`u-boot-xlnx`](../u-boot-xlnx/README.md) /
[`arm-trusted-firmware`](../arm-trusted-firmware/README.md) and pass the
paths via `BOOT_BIN_UBOOT=` / `BOOT_BIN_ATF=`.

## Guided wizard

`make guide` (or `./scripts/build-hdl.sh`) walks through:

0. **HDL release** (defaults to `HDL_RELEASE`)
1. **Project** — type a name, `list`/`?` for all, `filter <term>` to search
2. **Carrier board** for that project
3. **EDA tool** verification in your environment
4. **Parallel jobs**, output directory and **BOOT.BIN** generation
5. Summary with the equivalent `make … sdk-build` command, then confirm

## Script reference

```
scripts/build-hdl.sh --release <ref> --vivado <path|auto> \
    --project <name> --board <name> [--jobs N] [--dir-name build] \
    [--boot-bin [true|false]] [--boot-bin-uboot download] [--dry-run] [--clean]

scripts/build-hdl.sh [--release <ref>] --list | --list-projects | \
    --list-boards <project> | --list-tools | --check-tools
scripts/build-hdl.sh --interactive
```

`--dry-run` prints the tool environment and make commands without running
them. `--check-tools` exits non-zero when Vivado cannot be resolved for the
release. `make sdk-clean` runs the project's `make clean` with the same
release/tool resolution.

## Non-interactive examples

```bash
# fmcomms2 on ZedBoard (Vivado) with BOOT.BIN, 2023_R2 release
make sdk-build HDL_RELEASE=hdl_2023_r2 HDL_PROJECT=fmcomms2 HDL_BOARD=zed BUILD_BOOT_BIN=true

# cn0561 on DE10-Nano (Intel Quartus)
make sdk-build HDL_PROJECT=cn0561 HDL_BOARD=de10nano

# ad738x_fmc on Lattice Certus-NX (Radiant)
make sdk-build HDL_PROJECT=ad738x_fmc HDL_BOARD=lfcpnx

# explicit Vivado for an unlisted branch
make sdk-build HDL_RELEASE=main VIVADO=/opt/Xilinx/2025.2/Vivado HDL_PROJECT=fmcomms2 HDL_BOARD=zcu102
```

## Verification

`tests/test_hdl_guide.py` exercises release switching, Vivado resolution,
dirty-worktree refusal, dry-run and clean against a fake `hdl/` git repo — no
network, no EDA tools. Set `CIM_NETWORK=1` (and `CIM_BIN` if `cim` is not on
PATH) to also run a real `cim init` + generated-Makefile check that clones the
actual hdl repository.
