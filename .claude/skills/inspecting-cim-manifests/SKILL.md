---
name: inspecting-cim-manifests
description: Use when answering questions about what this repo's cim targets can build, without building — "which boards support fmcomms2", "what Vivado does hdl_2026_r1 need", "which devicetree pairs with adv7511_zed", "what will this build actually run", "is there a prebuilt for X", target variables/defaults, or when a script/CI needs machine-readable (JSON) answers instead of the interactive `make guide` wizards.
---

# Inspecting cim manifests (no builds)

Answer from JSON queries, not by reading scripts or driving `make guide` /
`make guide-dry-run`, which are interactive. Workspace setup lives in
`building-cim-targets`.

## Where each query works

| You are in | Works | Does NOT work |
|---|---|---|
| repo checkout (no workspace) | `scripts/manifest-tool.py`, `targets/hdl/hdl-prebuilt.py`, `targets/u-boot-xlnx/build-uboot.sh`, `targets/arm-trusted-firmware/build-atf.sh`, `targets/adi-linux/{build-kernel,guide-linux}.py` | `targets/hdl/build-hdl.sh`, because it needs a workspace `hdl/` clone. Never run it from a checkout. |
| cim workspace | `make *-json` / `make list-*` for that target | other targets' make verbs |
| nowhere | `cim list-targets --source https://github.com/tfcollins/datax-manifests.git [-t X]`, GitHub API | — |

`cim list-targets --source "$PWD"` lists target names. With `-t X` it needs
the git URL; a local path prints "No versions found".

## Question → command

| Question | Command |
|---|---|
| targets, variables + defaults, deps, `extends` | `python3 scripts/manifest-tool.py --list-targets --json` · `--target X --json` · `--all --json` |
| carrier boards for a project, **before any workspace** | GitHub API, see below |
| same, in an hdl/hdl-boot workspace (adds tool + boot arch) | `make list-boards-json HDL_PROJECT=<p> HDL_RELEASE=<r>` |
| all project×board combos / tools | `make list-combos-json` · `make list-tools-json` · `make check-tools-json` (workspace) |
| Vivado for a release | `hdl_2023_r2`→2023.2, `hdl_2026_r1`/`main`→2025.1; anything else needs `VIVADO=` |
| is there a prebuilt (Kuiper 2026_R1 only)? | `python3 targets/hdl/hdl-prebuilt.py --list --json` (keys `name`, `board`, `arch`) · `--check --project P --board B --json` |
| devicetree(s) for a design (text table) | `python3 targets/adi-linux/build-kernel.py --list-dts --release 2026_R1 --platform zynq --hdl-project <p>_<board>` (workspace: `make list-dts …`) |
| the one devicetree + full kernel plan, as JSON | `python3 targets/adi-linux/guide-linux.py --release 2026_R1 --platform zynq --dts auto --hdl-project <p>_<board> --json` → `.dts`, `.artifact_dir`, `.commands.build`; exits non-zero listing the choices when there are several |
| u-boot preset/ref/defconfig for a design | `bash targets/u-boot-xlnx/build-uboot.sh --board auto --hdl-project <p> [--hdl-board <b>] --release <r> --dry-run --json` · all presets: `--list --json` |
| bl31 tag for a release | `bash targets/arm-trusted-firmware/build-atf.sh --plat zynqmp --release <r> --dry-run --json` |
| exact command a workspace build will run | `make config-json …same vars as sdk-build…` (hdl, adi-linux, u-boot-xlnx, atf) · hdl-boot: `make boot-config-json`. From a checkout, the script-level `--dry-run --json` / `guide-linux.py --json` rows above give the same plan with checkout paths |

Boards per project/release without a workspace, as a JSON array:

```bash
gh api 'repos/analogdevicesinc/hdl/contents/projects/fmcomms2?ref=hdl_2026_r1' \
  -q '[.[] | select(.type=="dir" and .name!="common") | .name]'
```

This gives names only. Boot arch per board needs a workspace
(`make list-boards-json`) or this rule of thumb:
- **zynq:** `zed`, `zc702`, `zc706`, `coraz7s`.
- **zynqmp:** `zcu102`, `k26`/`kv260`, and SOMs such as `jupiter_sdr`.
- **versal:** `vck190`, `vmk180`, `vpk180`.
- **none (no BOOT.BIN):** `kcu105`, `vcu118`, `ac701`, and Intel (`a10soc`,
  `s10soc`, `de10*`).

For boards that have a prebuilt, `hdl-prebuilt.py --list --json` gives the
exact `arch`.

## Joining answers across targets

Each target names the same design differently:

| Thing | hdl / hdl-boot | adi-linux CSV | prebuilts | u-boot |
|---|---|---|---|---|
| design | `HDL_PROJECT=adv7511 HDL_BOARD=zed` | `adv7511_zed` (carrier-less: `jupiter_sdr`) | `name=adv7511 board=zed` | `--hdl-project adv7511 --hdl-board zed` |
| release | `hdl_2026_r1` | `KERNEL_RELEASE=2026_R1` | always 2026.1.0 | `--release hdl_2026_r1` |
| platform | from `--boot-arch` | CSV `zynqu` = `zynqmp` | `arch` | — |

- **2023_R2:** there are no prebuilts and no 2023 boot-pairings CSV (it falls
  back to the 2026_R1 one).
- **No BOOT.BIN and no adi-linux kernel:** boards whose boot arch is `none`
  (MicroBlaze `kcu105`, `vcu118`, and Intel/Lattice).

## Reading the output

- **`--json` / `*-json` commands:** stdout is JSON and stderr carries
  `[WARN]`/notes. Use `2>/dev/null` (or a separate stderr capture) when piping
  into `json.load` or `jq`.
- **`--list-dts` and the plain `list-*` verbs print text tables.** Don't parse
  them.
- **Script paths:** `scripts/<x>` in a workspace is `targets/<t>/<x>` in a
  checkout (`scripts/manifest-tool.py` is the exception: it lives in the repo).
- **A non-zero exit means the answer is an error.** Don't parse stdout then.
- **zsh (this host's shell):** `$cmd` with spaces and unquoted `*` / `[]` don't
  work the way bash does. Wrap loops in `bash -c '…'` and quote the `gh api`
  path.
- **Board lists follow the branch tip** of the named release. Say which
  release you queried.
