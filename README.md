# datax-manifests

[cim](https://github.com/analogdevicesinc/cim) manifests for Analog Devices
HDL and Linux kernel workspaces. Each target under `targets/` describes the
repositories, host dependencies and build recipes cim uses to set up a
ready-to-build workspace; the targets work with upstream cim — no fork
required.

## Getting started

Install cim following the
[cim README](https://github.com/analogdevicesinc/cim/blob/main/README.md)
(`cargo install --git https://github.com/analogdevicesinc/cim dsdk-cli`).

```bash
# 1. List the targets in this repository
cim list-targets --source https://github.com/tfcollins/datax-manifests.git

# 2. Inspect one
cim list-targets --source https://github.com/tfcollins/datax-manifests.git -t hdl

# 3. Initialize a workspace (add --install to also install host dependencies)
cim init --source https://github.com/tfcollins/datax-manifests.git -t hdl --workspace ~/cim-hdl
cd ~/cim-hdl && cim makefile
```

Use `--source /path/to/datax-manifests` for a local checkout, or
`--version <commit>` to pin a reviewed revision of this repository.

## Targets

| Target | Description |
|---|---|
| [hdl](targets/hdl/README.md) | ADI HDL reference designs for Vivado / Quartus / Radiant. `HDL_RELEASE` selects any `analogdevicesinc/hdl` branch, tag or commit (default `hdl_2026_r1`) and the matching Vivado; guided wizard and project/board matrix inspection via `make guide`, `make list-combos`. |
| [hdl-boot](targets/hdl-boot/README.md) | `extends: hdl` — same workspace plus `u-boot-xlnx` and `arm-trusted-firmware` clones; `sdk-build` builds u-boot.elf and bl31.elf from source for the selected design before the HDL, so BOOT.BIN uses no prebuilt downloads. |
| [u-boot-xlnx](targets/u-boot-xlnx/README.md) | `u-boot.elf` from `analogdevicesinc/u-boot-xlnx` for ADI / AMD Zynq boards (`UBOOT_BOARD` presets: zed, zcu102, jupiter_sdr, adrv2crr_fmc, pluto, …). Builds on any x86 host. |
| [arm-trusted-firmware](targets/arm-trusted-firmware/README.md) | `bl31.elf` from `Xilinx/arm-trusted-firmware` for ZynqMP / Versal, tag matched to the Vivado release. |
| [adi-linux](targets/adi-linux/README.md) | Kernel-only `analogdevicesinc/linux` builds for Zynq / ZynqMP from checksum-pinned source and toolchains. `KERNEL_RELEASE` (`2023_R2`, `2026_R1`) and `KERNEL_PLATFORM` select at make time; publishes an `artifacts.json` contract for pyadi-dt. |

## Repository structure

```
.
├── shared/templates/     # Starter templates for new targets
├── targets/
│   └── <name>/
│       ├── sdk.yml                # Manifest (gits, variables, copy_files, build/clean)
│       ├── os-dependencies.yml    # Host OS packages
│       ├── README.md              # Target documentation
│       └── ...                    # Helper scripts / make includes copied into the workspace
└── tests/                # Offline contract tests for the helper scripts
```

## Adding a target

1. `mkdir targets/<name>` and copy `shared/templates/sdk.yml.template` to
   `targets/<name>/sdk.yml`; add `os-dependencies.yml` (and
   `python-dependencies.yml` if needed) from the templates.
2. Helper scripts and make includes live next to `sdk.yml` and are delivered
   with `copy_files:` / `makefile_include:` — keep the target self-contained
   (no `../` references in `sdk.yml`) so `cim init` from a git source works.
   To share a script between targets, symlink it (see `targets/hdl-boot/`).
3. To build on another target use `extends: <target>` plus `overlay:` (see
   `targets/hdl-boot/sdk.yml`); cim merges both into one workspace. Use an
   absolute `--source` path when initializing locally — with `--source .`
   upstream cim 1.2.4 does not find the base target's local `copy_files`.
4. Document it in `targets/<name>/README.md` and add a row above.
5. Add offline tests under `tests/` where the target carries scripts.

## Testing

```bash
python3 -m unittest discover -s tests -v
```

Tests that need a `cim` binary look at `CIM_BIN` or `PATH` and skip
otherwise; set `CIM_NETWORK=1` to also run the cases that clone real
repositories.

CI (`.github/workflows/ci.yml`) runs four jobs against the pinned upstream
cim release:

| Job | Runner | What |
|---|---|---|
| `lint` | GitHub-hosted | shellcheck, `py_compile`, YAML parse, actionlint |
| `test` | GitHub-hosted | adi-linux tests, `cim init` smoke of `adi-linux` |
| `boot-components` | GitHub-hosted (matrix) | real `u-boot.elf` builds for `jupiter_sdr` / `zed` and `bl31.elf` for ZynqMP via the standalone targets; artifacts uploaded |
| `hdl` | self-hosted `hdl-dev-2` (labels `hdl-dev-2`, `vivado`) | hdl tests incl. real `cim init`, `make check-tools` for both releases against the installed Vivado 2023.2 / 2025.1, dry-run builds, `hdl-boot` smoke-init |

A real Vivado build runs only on manual dispatch: **Actions → CI → Run
workflow** with `build` checked (inputs `release` / `project` / `board`,
default `hdl_2023_r2` / `fmcomms2` / `zed`).

## License

Apache 2.0 — see [LICENSE](LICENSE).
