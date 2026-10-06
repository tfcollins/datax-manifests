# `u-boot-xlnx` — U-Boot for ADI / AMD Zynq boards from source

Builds `u-boot.elf` from
[analogdevicesinc/u-boot-xlnx](https://github.com/analogdevicesinc/u-boot-xlnx)
for the carriers and SOM designs that the HDL target's BOOT.BIN flow otherwise
downloads prebuilt from ADI. Standalone use, or composed with the HDL build via
the [`hdl-boot`](../hdl-boot/README.md) target.

| File | Purpose |
|---|---|
| `sdk.yml` | `u-boot-xlnx` git, `UBOOT_*` variables, `sdk-build` → `make uboot-build` |
| `os-dependencies.yml` | u-boot host build deps + both cross compilers |
| `build-uboot.sh` | Preset table, ref switching, out-of-tree build; copied to `scripts/` |
| `uboot.mk` | `make uboot-build / uboot-dry-run / uboot-list / uboot-clean` |

## Quick start

```bash
cim init --target u-boot-xlnx --source https://github.com/tfcollins/datax-manifests.git --workspace ~/cim-uboot --install
cd ~/cim-uboot && cim makefile

make uboot-list                                   # preset table
make sdk-build UBOOT_BOARD=zcu102 UBOOT_RELEASE=hdl_2026_r1
make sdk-build UBOOT_BOARD=jupiter_sdr
ls -l u-boot-xlnx/u-boot.elf
```

## Presets

`UBOOT_BOARD` selects the ref, defconfig, device tree and cross compiler.
Xilinx reference boards track the `xlnx_rebase_*` tag matching the HDL /
Vivado release (`UBOOT_RELEASE`: `hdl_2023_r2` → 2023.2, `hdl_2026_r1` →
2025.1); ADI boards live on their own branches and ignore `UBOOT_RELEASE`.

| `UBOOT_BOARD` | ref | defconfig | `DEVICE_TREE` |
|---|---|---|---|
| `zed`, `zc702`, `zc706` | per release | `xilinx_zynq_virt_defconfig` | `zynq-<board>` |
| `zcu102` | per release | `xilinx_zynqmp_virt_defconfig` | `zynqmp-zcu102-rev1.0` |
| `k26`, `kv260` | per release | `xilinx_zynqmp_kria_defconfig` | `zynqmp-smk-k26-revA` |
| `jupiter_sdr` | `jupiter-sdr` (xilinx-v2023.1 base) | `xilinx_zynqmp_virt_defconfig` | `zynqmp-jupiter-sdr` |
| `adrv2crr_fmc`, `adrv2crr_fmcomms8` | `master` | `adi_zynqmp_adrv9009_zu11eg_adrv2crr_fmc_defconfig` | (defconfig default) |
| `coraz7s` | `master` | `zynq_coraz7_defconfig` | — |
| `ccbob_*`, `ccfmc_*`, `adrv9361z7035` | `master` | `zynq_adrv9361_defconfig` | — |
| `adrv9364z7020` | `master` | `zynq_adrv9364_defconfig` | — |
| `pluto`, `m2k` | `pluto` | `zynq_pluto_defconfig` / `zynq_m2k_defconfig` | — |

This table is the maintainers' reading of where ADI keeps each board's
u-boot; the ADI branches are older u-boot bases than the Vivado release, which
is what ADI's prebuilt `u-boot.elf` files are built from as well.

`UBOOT_BOARD=auto` with `UBOOT_HDL_PROJECT` / `UBOOT_HDL_BOARD` derives the
preset from an HDL design (carrier-less designs such as `jupiter_sdr` by
project, everything else by carrier). Boards without a preset:

```bash
make sdk-build UBOOT_REF=xlnx_rebase_v2025.01_2025.1 UBOOT_DEFCONFIG=xilinx_zynqmp_virt_defconfig UBOOT_DEVICE_TREE=zynqmp-zcu106-revA
```

Any of `UBOOT_REF` / `UBOOT_DEFCONFIG` / `UBOOT_DEVICE_TREE` /
`UBOOT_CROSS_COMPILE` overrides the preset value individually.

## Notes

* Switching `UBOOT_BOARD` switches the `u-boot-xlnx/` checkout to the preset's
  ref (fetching it if needed) and refuses to touch a dirty worktree.
* `CROSS_COMPILE` is `arm-linux-gnueabihf-` for Zynq-7000 and
  `aarch64-linux-gnu-` for ZynqMP; both come from `os-dependencies.yml`
  (`cim install os-deps` or `cim init --install`).
* The 2018-era ADI branches (`master`, `pluto`) may need an older host GCC for
  their host tools; CI builds the `jupiter_sdr` and `zed` presets on Ubuntu 24.04.
* Output is `u-boot-xlnx/u-boot.elf` (plus `u-boot.bin`, `u-boot.dtb`), ready
  for `BOOT_BIN_UBOOT=` in the [`hdl`](../hdl/README.md) target.
