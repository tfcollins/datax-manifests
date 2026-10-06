# `arm-trusted-firmware` — BL31 for ZynqMP / Versal from source

Builds `bl31.elf` from
[Xilinx/arm-trusted-firmware](https://github.com/Xilinx/arm-trusted-firmware)
with the same settings ADI's `build_zynqmp_boot_bin.sh` uses for its
"download" path (`PLAT=<plat> RESET_TO_BL31=1`, tag `xilinx-v<Vivado>`).
Standalone use, or composed with the HDL build via
[`hdl-boot`](../hdl-boot/README.md).

| File | Purpose |
|---|---|
| `sdk.yml` | `arm-trusted-firmware` git, `ATF_*` variables, `sdk-build` → `make atf-build` |
| `os-dependencies.yml` | `gcc-aarch64-linux-gnu` |
| `build-atf.sh` | Release→tag mapping, ref switching, build; copied to `scripts/` |
| `atf.mk` | `make atf-build / atf-dry-run / atf-clean` |

## Quick start

```bash
cim init --target arm-trusted-firmware --source https://github.com/tfcollins/datax-manifests.git --workspace ~/cim-atf --install
cd ~/cim-atf && cim makefile
make sdk-build ATF_PLAT=zynqmp ATF_RELEASE=hdl_2026_r1
ls -l arm-trusted-firmware/bl31.elf
```

## Variables

| Variable | Default | Meaning |
|---|---|---|
| `ATF_PLAT` | `zynqmp` | `zynqmp` or `versal` |
| `ATF_RELEASE` | `hdl_2026_r1` | HDL / Vivado release → tag (`hdl_2023_r2` → `xilinx-v2023.2`, `hdl_2026_r1` → `xilinx-v2025.1`) |
| `ATF_REF` | (empty) | Explicit tag/branch/sha, overrides `ATF_RELEASE` |
| `ATF_CONSOLE` | `cadence0` | ZynqMP UART used by BL31 (`cadence1` for boards wired to UART1) |

The result is copied to `arm-trusted-firmware/bl31.elf` (from
`build/<plat>/release/bl31/bl31.elf`) so consumers have one stable path —
`BOOT_BIN_ATF=` in the [`hdl`](../hdl/README.md) target. Zynq-7000 designs do
not use BL31.
