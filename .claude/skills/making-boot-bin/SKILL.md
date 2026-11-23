---
name: making-boot-bin
description: Use when someone needs a BOOT.BIN (or bitstream/XSA) for an ADI HDL design on a Zynq-7000, ZynqMP or Versal board from this repo's hdl / hdl-boot targets — "BOOT.BIN for adrv9009 on zcu102", "no Vivado on this machine", "prebuilt bitstream", "u-boot / bl31 from source", HDL_BITSTREAM=download, BOOT_BIN_UBOOT / BOOT_BIN_ATF choices, or a BOOT.BIN that seems stale or from the wrong release.
---

# Making a BOOT.BIN

Workspace setup, release → Vivado mapping and the failure table live in
`building-cim-targets`. This skill helps you pick the right path and tells
you where the file lands. Tutorials: `doc/source/tutorials/fmcomms2-zed-boot-bin.rst`
and `jupiter-sdr-from-source.rst`.

## Pick the path

Ask, or infer, three things first: the release, whether Vivado **with
Vitis** is installed, and whether u-boot/ATF must come from source.

| Need | Target | Xilinx tools | Command |
|---|---|---|---|
| Fastest; any BOOT.BIN for the design | none: `git clone --depth 1 https://github.com/tfcollins/datax-manifests.git` | none | `python3 targets/hdl/hdl-prebuilt.py --extract --project P --board B --output DIR` |
| Same, inside an hdl workspace | `hdl` | none | `make sdk-build HDL_PROJECT=P HDL_BOARD=B HDL_BITSTREAM=download BUILD_BOOT_BIN=true` |
| Bitstream built locally + ADI prebuilt u-boot (ZynqMP/Versal: bl31 is cloned and built, needs `gcc-aarch64-linux-gnu`) | `hdl` | Vivado + Vitis | `make sdk-build HDL_RELEASE=R HDL_PROJECT=P HDL_BOARD=B BUILD_BOOT_BIN=true` |
| Everything from source (u-boot, bl31, HDL) | `hdl-boot` | Vivado + Vitis | `make sdk-build HDL_RELEASE=R HDL_PROJECT=P HDL_BOARD=B` |
| Prebuilt bitstream + u-boot/bl31 from source | `hdl-boot` | **Vitis still required** (`xsct`, `bootgen`) | `make sdk-build HDL_PROJECT=P HDL_BOARD=B HDL_BITSTREAM=download` |

**Prebuilts exist only for Kuiper 2026_R1.** `hdl-prebuilt.py` always uses
the `adi-*-boot_2026.1.0` packages, whatever `HDL_RELEASE` says.
- **Other releases:** a user who needs a 2023_R2 BOOT.BIN has no prebuilt
  path. Say so, and offer either a Vivado 2023.2 + Vitis host or the 2026_R1
  prebuilt.
- **Don't mislabel it:** never pass a 2026_R1 prebuilt off as 2023_R2.
  `make sdk-build HDL_RELEASE=hdl_2023_r2 HDL_BITSTREAM=download …` does
  exactly that: it unpacks 2026_R1 files into a tree checked out at 2023_R2.
  Newer `build-hdl.sh` prints a `[WARN]`; older copies are silent. Never
  combine `HDL_RELEASE=hdl_2023_r2` with `HDL_BITSTREAM=download`.

**No Vivado/Vitis on the machine?**
- **What works:** only the first two rows produce a BOOT.BIN.
- **Partial work:** u-boot.elf and bl31.elf still build without Xilinx tools
  (`u-boot-xlnx` / `arm-trusted-firmware` targets, or `make boot-uboot boot-atf`
  in hdl-boot). Package them later on a Vitis host with
  `BOOT_BIN_UBOOT=/path/u-boot.elf BOOT_BIN_ATF=/path/bl31.elf`.

## Check the design before building

```bash
# repo checkout (first use downloads the Kuiper package index into ~/.cache/cim/hdl-boot-debs)
python3 targets/hdl/hdl-prebuilt.py --check --project P --board B --json   # prebuilt exists? arch?
# inside the hdl / hdl-boot workspace only (build-hdl.sh needs the workspace hdl/ clone)
make boot-dry-run HDL_RELEASE=R HDL_PROJECT=P HDL_BOARD=B                  # hdl-boot: u-boot preset + ATF tag
bash scripts/build-hdl.sh -r hdl_2026_r1 -p P [-b B] --boot-bin true --dry-run   # exact commands; no -b for carrier-less
```

`inspecting-cim-manifests` covers the board lists and JSON queries.

| Design kind | Notes |
|---|---|
| Zynq-7000 (`zed`, `zc702`, `zc706`, `coraz7s`) | no bl31; `build_boot_bin.sh` |
| ZynqMP (`zcu102`, `k26`, SOMs) | needs bl31 (`BOOT_BIN_ATF`); `build_zynqmp_boot_bin.sh` |
| Carrier-less (`jupiter_sdr`, `pluto`, `m2k`, …) | `HDL_PROJECT` only; leave out `HDL_BOARD` |
| Versal (`vck190`, `vmk180`, `vpk180`) | bl31 + `build_versal_boot_bin.sh`; no adi-linux kernel |
| MicroBlaze / Intel / Lattice (`kcu105`, `vcu118`, `de10…`) | no BOOT.BIN. Bitstream only |

## Where the BOOT.BIN is

| Path taken | File |
|---|---|
| `hdl-prebuilt.py --extract --output DIR` | `DIR/BOOT.BIN` (+ `system_top.bit`/`.xsa`, dtbs) |
| `HDL_BITSTREAM=download`, all prebuilt | `hdl/projects/P[/B]/build/BOOT.BIN`, copied to `hdl/projects/P[/B]/BOOT.BIN` |
| any path that packages (Vivado build, or u-boot/bl31 from source) | `hdl/projects/P[/B]/output_boot_bin/BOOT.BIN` |

(`build` is `DIR_NAME`.)
- **Packaged path:** when u-boot or bl31 came from source, only
  `output_boot_bin/BOOT.BIN` is valid.
- **Stale file:** a `build/BOOT.BIN` left over from an earlier prebuilt
  download still contains ADI's prebuilt u-boot. Check the timestamp before
  handing over either file.

## What "prebuilt u-boot" means

`BOOT_BIN_UBOOT=download` (`hdl` target) lets the packaging helper
(`build_boot_bin.sh` / `build_zynqmp_boot_bin.sh`) fetch ADI's u-boot.
- **Unpinned:** cim copies these helpers from wiki-scripts `main`, unpinned.
- **Version follows Vitis:** the helper picks the u-boot matching the
  installed Vitis version.
- **Release-exact u-boot:** use `hdl-boot`, or pass a `BOOT_BIN_UBOOT=/path`
  you built.

## Running it

- **Expected time:** Vivado builds take 30 min–2 h. Run `make sdk-build` in
  the background (watch-build) and report once.
- **Judge by the output, not the log:** the result is `[FAILED] … status N`
  or `[SUCCESS]`, but always confirm the BOOT.BIN path above exists and is new.
- **Kernel + devicetree:** for the same board, see `building-kernel-devicetree`
  (`hdl_2026_r1` ↔ `KERNEL_RELEASE=2026_R1`).
