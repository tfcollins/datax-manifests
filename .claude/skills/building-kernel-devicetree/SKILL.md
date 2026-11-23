---
name: building-kernel-devicetree
description: Use when asked for an ADI Linux kernel image, a devicetree blob (system.dtb / devicetree.dtb), or kernel artifacts for pyadi-dt from this repo's adi-linux target — "kernel for jupiter_sdr", "which dts goes with adv7511_zed", "check every zynqmp devicetree compiles", "ADIDT_KERNEL_ARTIFACTS", KERNEL_DTS / HDL_PROJECT lookup errors such as "several devicetrees".
---

# Kernel + devicetree with adi-linux

Workspace setup and the general failure table live in `building-cim-targets`.
This skill covers selecting the devicetree, the build modes, and where the
artifacts land. Full reference: `targets/adi-linux/README.md`.

## Pass the release and platform on every call

The defaults are `KERNEL_RELEASE=2023_R2` and `KERNEL_PLATFORM=zynq`.
- **What goes wrong:** a 2026_R1 devicetree name with no `KERNEL_RELEASE`
  builds against the 2023_R2 kernel. It succeeds or fails, but never against
  the release you meant.
- **Rule:** every `make` below carries both variables, including `list-dts`
  and `dtb`.

| HDL release (hdl target) | `KERNEL_RELEASE` | Kernel source | pyadi-dt `ADIDT_CIM_RELEASE` |
|---|---|---|---|
| `hdl_2023_r2` | `2023_R2` | branch 2023_R2 (Linux 6.1) | `2023_R2` |
| `hdl_2026_r1` | `2026_R1` | tag xlnx_2026.1.0 (Linux 6.12) | `2026-R1` (hyphen) |

## 1. Pick the devicetree

```bash
make list-dts KERNEL_RELEASE=2026_R1 KERNEL_PLATFORM=zynqmp HDL_PROJECT=jupiter_sdr
```

| What you have | Set |
|---|---|
| exactly one DTS listed | `KERNEL_DTS=auto HDL_PROJECT=<p>`, or name it (`make dtb` honours `auto` only in copies whose `dtb` recipe forwards `HDL_PROJECT`; naming it always works) |
| several (jupiter_sdr: `zynqmp-jupiter-sdr`, `…-rx2tx2`; fmcomms2_zcu102: two) | `KERNEL_DTS=<one of them>`. `auto` errors "several devicetrees"; ask the user which one if it isn't obvious |
| a DTS not in the CSV | `KERNEL_DTS=<name>`. Accepted if the kernel tree has it |
| nothing (kernel only) | leave `KERNEL_DTS` and `HDL_PROJECT` empty |

- **CSV project names:** the CSV uses `<project>_<carrier>` (`adv7511_zed`,
  `fmcomms2_zcu102`). Carrier-less designs use the bare name (`jupiter_sdr`).
  This differs from the hdl target, which uses `HDL_PROJECT=adv7511 HDL_BOARD=zed`.
- **Platform names:** CSV platform `zynqu` means `zynqmp`.
- **Not buildable here:** MicroBlaze, Versal and Intel rows are listed but
  cannot be built by adi-linux.
- **Only one CSV:** only `boot_pairings_2026_r1.csv` exists. 2023_R2 lookups
  fall back to it, so confirm the DTS exists in the 6.1 tree.

## 2. Preview, then build

```bash
make config-json KERNEL_RELEASE=2026_R1 KERNEL_PLATFORM=zynqmp KERNEL_DTS=zynqmp-jupiter-sdr  # exact command, no prompts
make sdk-build   KERNEL_RELEASE=2026_R1 KERNEL_PLATFORM=zynqmp KERNEL_DTS=zynqmp-jupiter-sdr KERNEL_JOBS=8
```

| Mode | Command | Output |
|---|---|---|
| kernel + dtb | `make sdk-build … KERNEL_DTS=<dts>` | `<KERNEL_OUTPUT>/<dts>/artifacts.json` + `image-<gen>/{Image\|uImage, system.dtb\|devicetree.dtb}` |
| kernel only | `make sdk-build …` (no DTS) | `<KERNEL_OUTPUT>/artifacts.json` |
| dtb only (no kernel compile) | `make dtb … KERNEL_DTS=<dts> KERNEL_OUTPUT=dtb-check/<rel>/<plat>` | `<KERNEL_OUTPUT>/<dts>/<system\|devicetree>.dtb`, **no** artifacts.json |
| every CSV dtb for a platform | `make dtb … KERNEL_DTS=all KERNEL_OUTPUT=dtb-check/2026_R1/zynqmp` | one dir per DTS |

- **`KERNEL_OUTPUT` default:** `artifacts/<release>/<platform>`.
- **`make dtb` goes in its own folder:** give it a separate `KERNEL_OUTPUT`,
  single DTS or `all`. Otherwise the loose `<dts>/system.dtb` lands next to
  the real `artifacts.json` of the default output.
- **A sweep is all-or-nothing:** one `make` run, and any failing DTS fails it
  with no `.dtb` kept. Names missing from the kernel tree are rejected up
  front.
- **Missing-name list from a checkout:**
  `CIM_NETWORK=1 python3 -m unittest tests.test_adi_devicetree` lists every
  missing name at once, but still stops at the first compile error.
- **Timing:** each run re-extracts the pinned source and applies the
  defconfig. A full-platform sweep took about 2 min in CI.
- **Run time:** the first build downloads the pinned source and toolchain into
  `~/.cache/cim/adi-linux`. A kernel build takes minutes: run it in the
  background (watch-build).

## 3. Hand off to pyadi-dt

Never hand-assemble the manifest path. `--verify` checks the build offline
and prints the absolute `artifacts.json` path, which includes the `/<dts>`
level. Run it in the workspace; from a checkout the script is
`targets/adi-linux/build-kernel.py`.

```bash
export ADIDT_CIM_RELEASE=2026-R1
export ADIDT_KERNEL_ARTIFACTS_ZYNQMP="$(python3 scripts/build-kernel.py --release 2026_R1 \
    --platform zynqmp --output artifacts/2026_R1/zynqmp --dts zynqmp-jupiter-sdr --verify)"
```

- **Export only the platforms you built.** Only `_ZYNQ` and/or `_ZYNQMP`.
- **What pyadi-dt uses:** it reads `kernel_image` from the manifest and
  checks the release pins and the sha256. It compiles and stages its own
  `devicetree.dtb`.
- **The cim dtb:** it sits at `devicetree.path`, as a known-good reference
  or for your own boot media. Don't search the build folders for either
  file.

## Pairs with

`making-boot-bin` gives the BOOT.BIN for the same design. Use the matching
release (`hdl_2026_r1` ↔ `2026_R1`).
