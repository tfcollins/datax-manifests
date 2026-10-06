# `hdl-boot` — HDL + BOOT.BIN with u-boot and ATF built from source

`extends: hdl`. One workspace that clones `analogdevicesinc/hdl`,
`analogdevicesinc/u-boot-xlnx` and `Xilinx/arm-trusted-firmware`, builds
`u-boot.elf` and `bl31.elf` for the selected design, then builds the HDL and
produces a BOOT.BIN from those locally built parts instead of ADI's prebuilt
downloads. Everything the [`hdl`](../hdl/README.md) target does
(`HDL_RELEASE`, `HDL_PROJECT`, `HDL_BOARD`, `make guide`, `make list-combos`,
…) works unchanged here.

```
cim init -t hdl-boot …
make sdk-build HDL_PROJECT=jupiter_sdr
   ├─ u-boot-xlnx          → make boot-uboot   (scripts/build-uboot.sh, preset from the design)
   ├─ arm-trusted-firmware → make boot-atf     (scripts/build-atf.sh, zynqmp/versal; skipped for Zynq-7000)
   └─ scripts/build-hdl.sh … --boot-bin true --boot-bin-uboot $(WORKSPACE)/u-boot-xlnx/u-boot.elf
                                              --boot-bin-atf   $(WORKSPACE)/arm-trusted-firmware/bl31.elf
```

## Quick start

> **Local checkouts: use an absolute `--source`.** With upstream cim ≤ 1.2.4
> `cim init --source . -t hdl-boot` silently skips the base `hdl` target's
> `copy_files` (`build-hdl.sh`, `hdl.mk`) — you'll see
> `! Source file ./targets/hdl/build-hdl.sh does not exist, skipping copy` and
> `cim makefile` then has no `sdk-build` recipe. `--source "$PWD"` or a git URL
> works. Fixed upstream in
> [analogdevicesinc/cim#89](https://github.com/analogdevicesinc/cim/pull/89).

```bash
cim init --target hdl-boot --source https://github.com/tfcollins/datax-manifests.git --workspace ~/cim-hdl-boot --install
cd ~/cim-hdl-boot && cim makefile

make boot-dry-run HDL_PROJECT=jupiter_sdr        # show the u-boot / ATF resolution
make sdk-build    HDL_PROJECT=jupiter_sdr        # u-boot + bl31 + Vivado + BOOT.BIN
make sdk-build    HDL_PROJECT=fmcomms2 HDL_BOARD=zed HDL_RELEASE=hdl_2023_r2
```

## Guided wizard

`make guide` is the same wizard as the `hdl` target, made boot-aware by the
presence of the u-boot / ATF helpers in the workspace:

```
[Step 4/5] Configure Build Options
Generate BOOT.BIN binary (zynqmp)? [Y/n] >
Boot components (this workspace can build u-boot and ATF from source):
  u-boot:  jupiter-sdr / xilinx_zynqmp_virt_defconfig / zynqmp-jupiter-sdr
  ATF:     zynqmp @ xilinx-v2025.1
Build u-boot and ATF from source? [Y/n] (n = use ADI's prebuilt downloads) >

[Step 5/5] Build Configuration Summary
  Generate BOOT.BIN:     true (zynqmp)
  Boot components:       from source (u-boot: …; ATF: xilinx-v2025.1)
Equivalent CIM / Make command:
  make HDL_RELEASE=hdl_2026_r1 HDL_PROJECT=jupiter_sdr DIR_NAME=build MAKE_JOBS="-j8" BUILD_BOOT_BIN=true sdk-build
```

The u-boot preset, ref and device tree and the ATF platform/tag are derived
from the release, project and board chosen in the earlier steps — nothing
extra to answer. Answering `n` to "from source" appends
`BOOT_BIN_UBOOT=download BOOT_BIN_ATF=download`; a design with no u-boot
preset falls back to the download with a hint to set `UBOOT_REF` /
`UBOOT_DEFCONFIG` / `UBOOT_DEVICE_TREE`. Confirming runs `make sdk-build`
with those variables so u-boot and ATF are built (or skipped) before the HDL.
`BUILD_BOOT_BIN=false` or `BOOT_BIN_*=download` skip the source builds
entirely.

## How it composes

cim's `extends:` merges the `hdl` manifest with this one in a single
workspace; the two extra `gits:` each carry their own `build:` so the
generated Makefile has `u-boot-xlnx` and `arm-trusted-firmware` targets, and
`sdk-build` lists them in `depends_on`. The `overlay:` sets
`BUILD_BOOT_BIN=true` and points `BOOT_BIN_UBOOT` / `BOOT_BIN_ATF` at the
workspace-built files. The helper scripts are the same files as in the
standalone [`u-boot-xlnx`](../u-boot-xlnx/README.md) and
[`arm-trusted-firmware`](../arm-trusted-firmware/README.md) targets
(symlinked in this directory, as is `os-dependencies.yml` from `u-boot-xlnx`;
the `hdl` level's own `os-dependencies.yml` is installed too, since cim
processes every level's file).

| Variable | Default | Meaning |
|---|---|---|
| `UBOOT_BOARD` | `auto` | u-boot preset; `auto` derives it from `HDL_PROJECT` / `HDL_BOARD` |
| `UBOOT_REF`, `UBOOT_DEFCONFIG`, `UBOOT_DEVICE_TREE` | (empty) | Per-field overrides for boards without a preset |
| `ATF_PLAT` | `auto` | `zynqmp` / `versal`; `auto` asks `build-hdl.sh --boot-arch` |
| `ATF_REF`, `ATF_CONSOLE` | (empty), `cadence0` | As in the standalone target |

Release coupling: `HDL_RELEASE` drives the u-boot tag for Xilinx reference
boards and the ATF tag for everyone (`hdl_2023_r2` → 2023.2, `hdl_2026_r1` →
2025.1); ADI boards' u-boot comes from their fixed branches regardless.

Designs without a boot ROM (Kintex/Virtex, Intel, Lattice) have no u-boot
preset and no BL31 — use the plain `hdl` target for those. Overriding
`BOOT_BIN_UBOOT=download` on the command line falls back to ADI's prebuilt
blob for a single build without changing the manifest.

## Verification

`tests/test_boot_components.py` covers preset/ref resolution and the manifest
wiring offline; CI builds `u-boot.elf` for `jupiter_sdr` and `zed` and
`bl31.elf` for ZynqMP on a hosted runner, and smoke-inits this target on
hdl-dev-2. A full `hdl-boot` build with Vivado is the manual dispatch job.
