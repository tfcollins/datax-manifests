---
name: building-cim-targets
description: Use when initializing, building in, or debugging a cim workspace for any target in this repo (hdl, hdl-boot, u-boot-xlnx, arm-trusted-firmware, adi-linux) — "cim init fails", "set up a workspace", "switch HDL release", a standalone u-boot.elf / bl31.elf build, or a build that printed Error 127 / gnutls.h / LFS smudge / "worktree is dirty" errors. For a BOOT.BIN use making-boot-bin; for a kernel or devicetree use building-kernel-devicetree; for questions answered without building use inspecting-cim-manifests.
---

# Building cim targets

Each `targets/<name>/README.md` is the full reference; this is the fast path
plus the pitfalls that cost time. Do not re-derive these from the scripts.

## Workspace setup

```bash
cim init -t <target> --source "$PWD" --workspace <dir> --yes --install   # not --source .  (cim#89)
cd <dir> && cim makefile
```

- Always an **absolute** `--source` (or the git URL). `--source .` makes
  cim ≤1.2.4 skip base-level `copy_files` under `extends:` (hdl-boot
  carries its own copies, other derived targets would silently lose files).
- `--install` (or later `cim install os-deps --yes`) is what installs
  `os-dependencies.yml`. Without it u-boot dies with
  `gnutls/gnutls.h: No such file` — check first with
  `bash scripts/build-uboot.sh --board <preset> --check-deps`
  (`make uboot-check-deps` exists only in a standalone `u-boot-xlnx` workspace).
- `GIT_LFS_SKIP_SMUDGE=1 cim init …` whenever `git lfs version` works
  (picard has it in `~/.local/bin`) — hdl has missing LFS objects upstream
  and the clone fails otherwise.

## Per-target fast path

| Target | Inspect first | Build |
|---|---|---|
| `hdl` | `make check-tools`, `make list-combos [HDL_RELEASE=…]`, `make list-boards HDL_PROJECT=x`, `make guide` | `make sdk-build HDL_RELEASE=hdl_2023_r2 HDL_PROJECT=fmcomms2 HDL_BOARD=zed [BUILD_BOOT_BIN=true]` |
| `hdl-boot` | `make boot-dry-run HDL_PROJECT=jupiter_sdr`, `make guide` | `make sdk-build HDL_PROJECT=jupiter_sdr` (u-boot → bl31 → Vivado → BOOT.BIN) |
| `u-boot-xlnx` | `make uboot-list`, `make uboot-dry-run UBOOT_BOARD=…`, `make uboot-check-deps` | `make sdk-build UBOOT_BOARD=zcu102 UBOOT_RELEASE=hdl_2026_r1` → `u-boot-xlnx/u-boot.elf` |
| `arm-trusted-firmware` | `make atf-dry-run` | `make sdk-build ATF_PLAT=zynqmp ATF_RELEASE=hdl_2026_r1` → `arm-trusted-firmware/bl31.elf` |
| `adi-linux` | `make list-combos`, `make list-dts KERNEL_RELEASE=<rel> KERNEL_PLATFORM=<plat> [HDL_PROJECT=x]`, `make guide-dry-run` | `make sdk-build KERNEL_RELEASE=2026_R1 KERNEL_PLATFORM=zynqmp [KERNEL_DTS=zynqmp-jupiter-sdr] KERNEL_JOBS=4` → `artifacts/<rel>/<plat>[/<dts>]/` |

Questions answered without building ("which boards", "which Vivado", JSON
for scripts): `inspecting-cim-manifests`. Picking a BOOT.BIN path:
`making-boot-bin`. Kernel + devicetree: `building-kernel-devicetree`.

hdl/hdl-boot: dry-run before any real build — `bash scripts/build-hdl.sh … --dry-run`
(or `--dry-run --json`) prints the exact tool env + make + BOOT.BIN commands.

## Facts that are not obvious

- One workspace serves every release: `HDL_RELEASE` (and `UBOOT_RELEASE`,
  `ATF_RELEASE`, `KERNEL_RELEASE`) are make-time variables. The helper
  switches the `hdl/` clone (needs network the first time, refuses a dirty
  tree) and re-derives Vivado — don't re-init to change release.
- Carrier-less projects (`jupiter_sdr`, `pluto`, `m2k`, `sidekiqz2`,
  `usrpe31x`) take only `HDL_PROJECT`; `HDL_BOARD` is ignored with a warning.
- `HDL_RELEASE` → Vivado: `hdl_2023_r2`→2023.2, `hdl_2026_r1`/`main`→2025.1;
  anything else needs `VIVADO=/path`. `hdl-dev-2.local` has both
  (`/opt/Xilinx/Vivado/2023.2`, `/opt/Xilinx/2025.1/Vivado`); picard has 2025.1 only.
- BOOT.BIN paths, helpers and which tools each path needs: `making-boot-bin`.
- u-boot presets: Xilinx boards follow the release tag; ADI boards pin their
  own branches (`jupiter-sdr`, `master`, `pluto`). No preset → set
  `UBOOT_REF`/`UBOOT_DEFCONFIG`/`UBOOT_DEVICE_TREE` (or ADI's prebuilt via
  `BOOT_BIN_UBOOT=download`, which is unpinned — see `making-boot-bin`).
- Devicetree selection (`KERNEL_DTS`, the boot-pairings CSV): `building-kernel-devicetree`.
- A real Vivado build is 30 min–2 h: run it in the background (watch-build)
  and prefer the hdl-dev-2 runner (`workflow_dispatch` with `build: true`).

## When a build fails

| Symptom | Cause / fix |
|---|---|
| `/bin/sh: auto: not found`, Error 127 in `library.mk` | A make var leaked into the hdl sub-make. Fixed in `build-hdl.sh` ≥ commit 1057a46 — re-copy `targets/hdl/build-hdl.sh` into `scripts/`. |
| `[SUCCESS]` printed after errors | Same stale script; current one prints `[FAILED] … status N` and exits non-zero. |
| `Vivado not found` | `make check-tools HDL_RELEASE=…`; set `VIVADO=`. |
| `worktree is dirty; refusing to switch` | Commit/stash in `hdl/` (or `u-boot-xlnx/`); untracked build output is fine. |
| `No rule to make target 'guide'` | Workspace lacks `hdl.mk` → re-init with absolute `--source`. |
| IP build FAILED | Read `hdl/library/<ip>/<ip>_ip.log`; project: `…/<board>/build/vivado.log`. |

## Verify

`python3 -m unittest discover -s tests` (offline, ~20 s). Add `CIM_NETWORK=1`
to also run the real `cim init` cases.
