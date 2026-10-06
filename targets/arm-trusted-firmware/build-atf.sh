#!/usr/bin/env bash
# ==============================================================================
# Build bl31.elf from Xilinx/arm-trusted-firmware for ZynqMP or Versal
# ==============================================================================
# The ref defaults to the xilinx-v<version> tag matching the Vivado release the
# HDL was built with, which is what ADI's build_zynqmp_boot_bin.sh "download"
# path builds as well. Output: <workspace>/arm-trusted-firmware/bl31.elf
# (copied from build/<plat>/release/bl31/bl31.elf so consumers get one stable path)
# ==============================================================================

BOLD="\033[1m"
CYAN="\033[36m"
YELLOW="\033[33m"
RED="\033[31m"
GREEN="\033[32m"
RESET="\033[0m"

ATF_UPSTREAM_URL="https://github.com/Xilinx/arm-trusted-firmware.git"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT=""
for cand in "${SCRIPT_DIR}/.." "${PWD}"; do
    if [ -d "${cand}/arm-trusted-firmware" ]; then WORKSPACE_ROOT="$(cd "$cand" && pwd)"; break; fi
done
if [ -z "$WORKSPACE_ROOT" ]; then
    curr="${PWD}"
    while [ "$curr" != "/" ]; do
        if [ -d "$curr/arm-trusted-firmware" ]; then WORKSPACE_ROOT="$curr"; break; fi
        curr="$(dirname "$curr")"
    done
fi
if [ -z "$WORKSPACE_ROOT" ]; then
    echo -e "${RED}[ERROR]${RESET} Could not locate the arm-trusted-firmware/ checkout; run inside an initialized cim workspace." >&2
    exit 1
fi
ATF_DIR="${WORKSPACE_ROOT}/arm-trusted-firmware"

# Vivado/Vitis release -> ATF tag (same mapping as wiki-scripts build_zynqmp_boot_bin.sh)
atf_tag_for_release() {
    case "$1" in
        hdl_2023_r2|2023.2|2023_R2) echo "xilinx-v2023.2" ;;
        hdl_2026_r1|2025.1|2026_R1|main) echo "xilinx-v2025.1" ;;
        *) return 1 ;;
    esac
}

local_ref_commit() {
    local rel="$1" ref
    for ref in "refs/heads/${rel}" "refs/tags/${rel}" "refs/remotes/origin/${rel}" "${rel}"; do
        git -C "$ATF_DIR" rev-parse --verify -q "${ref}^{commit}" 2>/dev/null && return 0
    done
    return 1
}

ensure_ref() {
    local rel="$1"
    [ -e "${ATF_DIR}/.git" ] || { echo -e "${YELLOW}[WARN]${RESET} ${ATF_DIR} is not a git checkout; cannot switch to '${rel}'." >&2; return 0; }
    local head want
    head="$(git -C "$ATF_DIR" rev-parse HEAD 2>/dev/null)" || head=""
    if want="$(local_ref_commit "$rel")" && [ "$want" = "$head" ]; then return 0; fi
    if [ -n "$(git -C "$ATF_DIR" status --porcelain --untracked-files=no)" ]; then
        echo -e "${RED}[ERROR]${RESET} arm-trusted-firmware/ worktree is dirty; refusing to switch to '${rel}'." >&2
        exit 1
    fi
    echo -e "${CYAN}[INFO]${RESET} Switching arm-trusted-firmware/ to '${rel}'..." >&2
    if git -C "$ATF_DIR" fetch -q --depth 1 origin "$rel" 2>/dev/null \
        || git -C "$ATF_DIR" fetch -q origin "$rel" 2>/dev/null \
        || git -C "$ATF_DIR" fetch -q --depth 1 "$ATF_UPSTREAM_URL" "$rel" 2>/dev/null; then
        git -C "$ATF_DIR" checkout -q --detach FETCH_HEAD || exit 1
    else
        git -C "$ATF_DIR" fetch -q --unshallow origin 2>/dev/null || git -C "$ATF_DIR" fetch -q origin 2>/dev/null || true
        if ! git -C "$ATF_DIR" checkout -q --detach "$rel" 2>/dev/null; then
            echo -e "${RED}[ERROR]${RESET} Could not fetch or check out arm-trusted-firmware ref '${rel}'." >&2
            exit 1
        fi
    fi
}

show_help() {
    cat <<EOF
Build bl31.elf from Xilinx/arm-trusted-firmware

Usage: $(basename "$0") [--plat zynqmp|versal] [--release <hdl release>] [--ref <ref>] [options]

Options:
  -p, --plat <plat>        zynqmp (default) or versal
  -r, --release <rel>      HDL release (hdl_2023_r2 -> xilinx-v2023.2, hdl_2026_r1 -> xilinx-v2025.1)
  --ref <ref>              arm-trusted-firmware tag/branch/sha (overrides --release)
  --console <uart>         ZynqMP console: cadence0 (default) or cadence1
  --cross-compile <prefix> default aarch64-linux-gnu-
  -j, --jobs <N>
  --dry-run                Print the resolved ref and commands and exit
  --clean
  -h, --help
EOF
}

main() {
    local plat="${ATF_PLAT:-zynqmp}" release="${ATF_RELEASE:-hdl_2026_r1}" ref="" console="cadence0"
    local cross="aarch64-linux-gnu-" jobs="" dry_run="false" clean="false"
    while [ $# -gt 0 ]; do
        case "$1" in
            -p|--plat) plat="$2"; shift 2 ;;
            -r|--release) release="$2"; shift 2 ;;
            --ref) ref="$2"; shift 2 ;;
            --console) console="$2"; shift 2 ;;
            --cross-compile) cross="$2"; shift 2 ;;
            -j|--jobs) jobs="$2"; shift 2 ;;
            --dry-run) dry_run="true"; shift ;;
            --clean) clean="true"; shift ;;
            -h|--help) show_help; return 0 ;;
            *) echo -e "${RED}[ERROR]${RESET} Unknown option: $1" >&2; exit 1 ;;
        esac
    done
    case "$plat" in zynqmp|versal) ;; *) echo -e "${RED}[ERROR]${RESET} --plat must be zynqmp or versal (got '${plat}')." >&2; exit 1 ;; esac

    if [ "$clean" = "true" ]; then
        rm -rf "${ATF_DIR}/build" "${ATF_DIR}/bl31.elf"
        echo "Cleaned ${ATF_DIR}/build"
        return 0
    fi
    if [ -z "$ref" ] && ! ref="$(atf_tag_for_release "$release")"; then
        echo -e "${RED}[ERROR]${RESET} No arm-trusted-firmware tag known for release '${release}'; pass --ref explicitly." >&2
        exit 1
    fi
    jobs="${jobs:-$(nproc 2>/dev/null || echo 4)}"
    local make_args="PLAT=${plat} RESET_TO_BL31=1 CROSS_COMPILE=${cross}"
    [ "$plat" = "zynqmp" ] && make_args="${make_args} ZYNQMP_CONSOLE=${console}"
    local out="${ATF_DIR}/build/${plat}/release/bl31/bl31.elf"
    local published="${ATF_DIR}/bl31.elf"

    echo -e "${BOLD}${GREEN}arm-trusted-firmware build${RESET}"
    echo "  PLAT:          ${plat}"
    echo "  Ref:           ${ref}"
    echo "  CROSS_COMPILE: ${cross}"
    echo "  Output:        ${published}"
    if [ "$dry_run" = "true" ]; then
        echo -e "\n${YELLOW}[DRY-RUN] Commands that would be executed:${RESET}"
        echo "1) git -C \"${ATF_DIR}\" checkout ${ref}"
        echo "2) make -C \"${ATF_DIR}\" -j${jobs} ${make_args} bl31"
        echo "3) cp \"${out}\" \"${published}\""
        return 0
    fi
    if ! command -v "${cross}gcc" >/dev/null 2>&1; then
        echo -e "${RED}[ERROR]${RESET} ${cross}gcc not found. Install gcc-aarch64-linux-gnu." >&2
        exit 1
    fi
    ensure_ref "$ref"
    set -e
    make -C "$ATF_DIR" distclean >/dev/null 2>&1 || true
    # shellcheck disable=SC2086
    make -C "$ATF_DIR" -j"$jobs" $make_args bl31
    test -f "$out"
    cp "$out" "$published"
    echo -e "\n${BOLD}${GREEN}[SUCCESS]${RESET} ${published}"
}

main "$@"
