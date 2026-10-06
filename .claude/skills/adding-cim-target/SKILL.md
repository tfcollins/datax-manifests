---
name: adding-cim-target
description: Use when creating a new target under targets/, deriving one from another with extends:, adding a helper script or make include to a target, or when a change to a target needs matching tests, README, docs page and CI wiring in this repo.
---

# Adding or extending a cim target

A target is `targets/<name>/` with `sdk.yml` + `os-dependencies.yml` +
`README.md` plus whatever scripts it delivers via `copy_files:`. Look at
`targets/arm-trusted-firmware` (small) and `targets/hdl-boot` (extends)
before writing a new one.

## Shape of a target

| File | Rule |
|---|---|
| `sdk.yml` | `variables:` are `?=` in the generated Makefile — every knob is overridable on the command line. `gits.commit` cannot be a variable; a script switches refs at build time (`ensure_release()` in `build-hdl.sh` is the pattern). |
| `copy_files:` | Sources must live in the target dir. Share a file between targets with a **symlink** (`ln -s ../hdl/build-hdl.sh`), never `../` in `sdk.yml`. |
| `makefile_include:` | Put `make <verb>` helpers in `<name>.mk`; recipes call `scripts/<script> $(VARS)`. |
| scripts | bash, `shellcheck -S warning` clean, `--dry-run` that prints the exact commands, `--list` / `--check-*` for inspection, status messages on **stderr** so machine-readable output stays clean. |
| `os-dependencies.yml` | Everything the script needs; add a preflight in the script that names the missing package (see `check_host_deps` in `build-uboot.sh`). |

## Deriving with `extends:`

- Single parent; `overlay:` has `remove:`/`modify:`/`variables.set:`, no `add:`
  (new entries go in the normal sections).
- Per-git `build:` creates a Makefile target named after the git; order with
  `build: {commands: […], depends_on: [git-a, git-b]}`. `build:` is a
  whole-value override, so restate the base command.
- Re-declare any base-level local `copy_files` you depend on as your own
  (symlinks + `overlay.copy_files.remove`) — cim#89 drops them for a relative
  `--source`. `hdl-boot/sdk.yml` shows all of this.

## Every target change ships with

1. **Tests** in `tests/test_<target>.py`: offline, fake git repos in a tmp
   dir, run the real script with `--dry-run`, assert resolved values and
   error paths. Gate anything that clones real repos on `CIM_NETWORK`.
   `tests/test_boot_components.py` is the template.
2. **README.md** in the target dir — file table, quick start, variables
   table, non-obvious facts. It *is* the doc page: `doc/source/targets/<name>.md`
   is a one-line `{include}`; add it to `doc/source/index.rst` and to the
   table in the top-level README.
3. **CI**: add the target to the `list-targets` assertion; a `cim init`
   smoke (`--source "$PWD"`); real compiles only on hosted runners if they
   need no EDA tools, otherwise on the `hdl-dev-2` job.
4. Local checks before pushing:
   ```bash
   docker run --rm -v "$PWD:/mnt" koalaman/shellcheck:stable -S warning targets/<name>/*.sh
   docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest
   python3 -m unittest discover -s tests
   cim init -t <name> --source "$PWD" --workspace /tmp/ws --yes && (cd /tmp/ws && cim makefile && make -n sdk-build)
   ```

## Mistakes already made here

- Asserting a host-specific path in a test (`/opt/Xilinx/2023.2/Vivado`) —
  hdl-dev-2 has the other layout. Assert versions, not paths.
- `git add -A` sweeping a scratch workspace into a commit — workspaces are
  gitignored as `/test*/`, `/ws-*/`; init elsewhere.
- Quoting inside `bash -c "…"` strings: `(` must be escaped or avoided.
- `MAKEOVERRIDES=` does not stop command-line vars reaching sub-makes; unset
  `MAKEFLAGS MAKEOVERRIDES MFLAGS` before invoking a foreign tree's make.
