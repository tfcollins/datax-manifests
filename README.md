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
   (no `../` references) so `cim init` from a git source works.
3. Document it in `targets/<name>/README.md` and add a row above.
4. Add offline tests under `tests/` where the target carries scripts.

## Testing

```bash
python3 -m unittest discover -s tests -v
```

Tests that need a `cim` binary look at `CIM_BIN` or `PATH` and skip
otherwise; set `CIM_NETWORK=1` to also run the cases that clone real
repositories. CI installs upstream cim and runs everything, plus a
`cim init` smoke test for each target.

## License

Apache 2.0 — see [LICENSE](LICENSE).
