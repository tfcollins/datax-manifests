#!/usr/bin/env bash
# ==============================================================================
# Build u-boot.elf from analogdevicesinc/u-boot-xlnx for an ADI / AMD board
# ==============================================================================
# The workspace u-boot-xlnx/ clone is switched to the ref that carries the
# board's defconfig and device tree, then built out of tree. Presets cover the
# carriers and SOM designs ADI ships prebuilt u-boots for; anything else can be
# built by passing --ref/--defconfig/--device-tree explicitly.
#
# Output: <workspace>/u-boot-xlnx/u-boot.elf (plus u-boot.bin / u-boot.dtb)
# ==============================================================================

BOLD="\033[1m"
CYAN="\033[36m"
YELLOW="\033[33m"
RED="\033[31m"
GREEN="\033[32m"
RESET="\033[0m"

UBOOT_UPSTREAM_URL="https://github.com/analogdevicesinc/u-boot-xlnx.git"

# Locate the workspace (scripts/ lives next to u-boot-xlnx/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT=""
for cand in "${SCRIPT_DIR}/.." "${PWD}"; do
    if [ -d "${cand}/u-boot-xlnx" ]; then
        WORKSPACE_ROOT="$(cd "$cand" && pwd)"
        break
    fi
done
if [ -z "$WORKSPACE_ROOT" ]; then
    curr="${PWD}"
    while [ "$curr" != "/" ]; do
        if [ -d "$curr/u-boot-xlnx" ]; then WORKSPACE_ROOT="$curr"; break; fi
        curr="$(dirname "$curr")"
    done
fi
if [ -z "$WORKSPACE_ROOT" ]; then
    echo -e "${RED}[ERROR]${RESET} Could not locate the u-boot-xlnx/ checkout; run inside an initialized cim workspace." >&2
    exit 1
fi
UBOOT_DIR="${WORKSPACE_ROOT}/u-boot-xlnx"

# Xilinx reference boards track the u-boot-xlnx tag that matches the Vivado
# release the HDL was built with; ADI boards live on their own branches.
xlnx_tag_for_release() {
    case "$1" in
        hdl_2023_r2|2023.2|2023_R2) echo "xlnx_rebase_v2023.01_2023.2" ;;
        hdl_2026_r1|2025.1|2026_R1|main) echo "xlnx_rebase_v2025.01_2025.1" ;;
        *) return 1 ;;
    esac
}

# Preset table: board -> "<ref-or-RELEASE> <defconfig> <device-tree-or-> <cross-compile>"
# RELEASE means "the xlnx_rebase tag for --release".
preset() {
    case "$1" in
        zed)          echo "RELEASE xilinx_zynq_virt_defconfig zynq-zed arm-linux-gnueabihf-" ;;
        zc702)        echo "RELEASE xilinx_zynq_virt_defconfig zynq-zc702 arm-linux-gnueabihf-" ;;
        zc706)        echo "RELEASE xilinx_zynq_virt_defconfig zynq-zc706 arm-linux-gnueabihf-" ;;
        zcu102)       echo "RELEASE xilinx_zynqmp_virt_defconfig zynqmp-zcu102-rev1.0 aarch64-linux-gnu-" ;;
        k26|kv260)    echo "RELEASE xilinx_zynqmp_kria_defconfig zynqmp-smk-k26-revA aarch64-linux-gnu-" ;;
        jupiter_sdr)  echo "jupiter-sdr xilinx_zynqmp_virt_defconfig zynqmp-jupiter-sdr aarch64-linux-gnu-" ;;
        adrv2crr_fmc|adrv2crr_fmcomms8|adrv9009zu11eg)
                      echo "master adi_zynqmp_adrv9009_zu11eg_adrv2crr_fmc_defconfig - aarch64-linux-gnu-" ;;
        coraz7s)      echo "master zynq_coraz7_defconfig - arm-linux-gnueabihf-" ;;
        ccbob_cmos|ccbob_lvds|ccfmc_lvds|adrv9361z7035)
                      echo "master zynq_adrv9361_defconfig - arm-linux-gnueabihf-" ;;
        adrv9364z7020) echo "master zynq_adrv9364_defconfig - arm-linux-gnueabihf-" ;;
        pluto)        echo "pluto zynq_pluto_defconfig - arm-linux-gnueabihf-" ;;
        m2k)          echo "pluto zynq_m2k_defconfig - arm-linux-gnueabihf-" ;;
        *) return 1 ;;
    esac
}

PRESET_NAMES="zed zc702 zc706 zcu102 k26 kv260 jupiter_sdr adrv2crr_fmc adrv2crr_fmcomms8 coraz7s ccbob_cmos ccbob_lvds ccfmc_lvds adrv9364z7020 pluto m2k"

# Derive the preset name from an HDL project/board pair: carrier-less designs
# (jupiter_sdr, pluto, m2k) are identified by project, the rest by carrier.
board_from_hdl() {
    local proj="$1" board="$2"
    case "$proj" in
        jupiter_sdr|pluto|m2k) echo "$proj"; return 0 ;;
    esac
    if [ -z "$board" ] && preset "$proj" >/dev/null 2>&1; then
        echo "$proj"
    elif preset "$board" >/dev/null 2>&1; then
        echo "$board"
    else
        return 1
    fi
}

local_ref_commit() {
    local rel="$1" ref
    for ref in "refs/heads/${rel}" "refs/tags/${rel}" "refs/remotes/origin/${rel}" "${rel}"; do
        git -C "$UBOOT_DIR" rev-parse --verify -q "${ref}^{commit}" 2>/dev/null && return 0
    done
    return 1
}

# Check out $1 in u-boot-xlnx/, fetching it if needed; refuse on a dirty tree.
ensure_ref() {
    local rel="$1"
    [ -e "${UBOOT_DIR}/.git" ] || { echo -e "${YELLOW}[WARN]${RESET} ${UBOOT_DIR} is not a git checkout; cannot switch to '${rel}'." >&2; return 0; }
    local head want
    head="$(git -C "$UBOOT_DIR" rev-parse HEAD 2>/dev/null)" || head=""
    if want="$(local_ref_commit "$rel")" && [ "$want" = "$head" ]; then return 0; fi
    if [ -n "$(git -C "$UBOOT_DIR" status --porcelain --untracked-files=no)" ]; then
        echo -e "${RED}[ERROR]${RESET} u-boot-xlnx/ worktree is dirty; refusing to switch to '${rel}'." >&2
        exit 1
    fi
    echo -e "${CYAN}[INFO]${RESET} Switching u-boot-xlnx/ to '${rel}'..." >&2
    if git -C "$UBOOT_DIR" fetch -q --depth 1 origin "$rel" 2>/dev/null \
        || git -C "$UBOOT_DIR" fetch -q origin "$rel" 2>/dev/null \
        || git -C "$UBOOT_DIR" fetch -q --depth 1 "$UBOOT_UPSTREAM_URL" "$rel" 2>/dev/null; then
        git -C "$UBOOT_DIR" checkout -q --detach FETCH_HEAD || exit 1
        if git -C "$UBOOT_DIR" show-ref -q --verify "refs/remotes/origin/${rel}"; then
            git -C "$UBOOT_DIR" checkout -q -B "$rel" "origin/${rel}" || exit 1
        fi
    else
        git -C "$UBOOT_DIR" fetch -q --unshallow origin 2>/dev/null || git -C "$UBOOT_DIR" fetch -q origin 2>/dev/null || true
        if ! git -C "$UBOOT_DIR" checkout -q --detach "$rel" 2>/dev/null; then
            echo -e "${RED}[ERROR]${RESET} Could not fetch or check out u-boot-xlnx ref '${rel}' from ${UBOOT_UPSTREAM_URL}." >&2
            exit 1
        fi
    fi
}

show_help() {
    cat <<EOF
Build u-boot.elf from analogdevicesinc/u-boot-xlnx

Usage:
  $(basename "$0") --board <preset> [--release <hdl release>] [options]
  $(basename "$0") --ref <ref> --defconfig <name> [--device-tree <dts>] [--cross-compile <prefix>]
  $(basename "$0") --hdl-project <p> [--hdl-board <b>] [--release <r>]   # derive the preset

Options:
  -b, --board <preset>       One of: ${PRESET_NAMES}
                             or "auto" (requires --hdl-project/--hdl-board)
  -r, --release <rel>        HDL release the HDL was built with (hdl_2023_r2, hdl_2026_r1);
                             selects the u-boot-xlnx tag for Xilinx reference boards
  --ref <ref>                u-boot-xlnx branch/tag/sha (overrides the preset)
  --defconfig <name>         u-boot defconfig (overrides the preset)
  --device-tree <name>       DEVICE_TREE= value, or "-" for the defconfig default
  --cross-compile <prefix>   CROSS_COMPILE= prefix (default from preset / arch)
  -j, --jobs <N>             Parallel jobs (default: nproc)
  --hdl-project/--hdl-board  Used with --board auto to pick the preset
  --list                     Show the preset table and exit
  --dry-run                  Print the resolved ref/defconfig/commands and exit
  --clean                    make distclean in u-boot-xlnx/
  -h, --help

Examples:
  $(basename "$0") --board zcu102 --release hdl_2026_r1
  $(basename "$0") --board jupiter_sdr
  $(basename "$0") --board auto --hdl-project fmcomms2 --hdl-board zed --release hdl_2023_r2
EOF
}

cmd_list() {
    echo -e "${BOLD}u-boot-xlnx presets${RESET} (RELEASE = xlnx_rebase tag matching --release)"
    printf "%-20s %-28s %-48s %-24s %s\n" "BOARD" "REF" "DEFCONFIG" "DEVICE_TREE" "CROSS_COMPILE"
    for b in $PRESET_NAMES; do
        read -r p_ref p_defconfig p_dt p_cross < <(preset "$b")
        printf "%-20s %-28s %-48s %-24s %s\n" "$b" "$p_ref" "$p_defconfig" "$p_dt" "$p_cross"
    done
}

main() {
    local board="" release="${UBOOT_RELEASE:-hdl_2026_r1}" ref="" defconfig="" dt="" cross="" jobs=""
    local hdl_project="" hdl_board="" dry_run="false" clean="false"
    [ $# -eq 0 ] && { show_help; return 0; }
    while [ $# -gt 0 ]; do
        case "$1" in
            -b|--board) board="$2"; shift 2 ;;
            -r|--release) release="$2"; shift 2 ;;
            --ref) ref="$2"; shift 2 ;;
            --defconfig) defconfig="$2"; shift 2 ;;
            --device-tree) dt="$2"; shift 2 ;;
            --cross-compile) cross="$2"; shift 2 ;;
            -j|--jobs) jobs="$2"; shift 2 ;;
            --hdl-project) hdl_project="$2"; shift 2 ;;
            --hdl-board) hdl_board="$2"; shift 2 ;;
            --list) cmd_list; return 0 ;;
            --dry-run) dry_run="true"; shift ;;
            --clean) clean="true"; shift ;;
            -h|--help) show_help; return 0 ;;
            *) echo -e "${RED}[ERROR]${RESET} Unknown option: $1" >&2; exit 1 ;;
        esac
    done

    if [ "$clean" = "true" ]; then
        make -C "$UBOOT_DIR" distclean >/dev/null 2>&1 || true
        rm -f "$UBOOT_DIR/u-boot.elf"
        echo "Cleaned ${UBOOT_DIR}"
        return 0
    fi

    if [ "$board" = "auto" ] || { [ -z "$board" ] && [ -n "$hdl_project" ]; }; then
        if ! board="$(board_from_hdl "$hdl_project" "$hdl_board")"; then
            echo -e "${RED}[ERROR]${RESET} No u-boot preset for HDL project/board '${hdl_project}/${hdl_board}'." >&2
            echo "Pass --ref/--defconfig/--device-tree explicitly, or set UBOOT_BOARD to one of: ${PRESET_NAMES}" >&2
            exit 1
        fi
    fi

    local p_ref="" p_defconfig="" p_dt="" p_cross=""
    if [ -n "$board" ]; then
        if ! read -r p_ref p_defconfig p_dt p_cross < <(preset "$board"); then
            echo -e "${RED}[ERROR]${RESET} Unknown board preset '${board}'. Known: ${PRESET_NAMES}" >&2
            exit 1
        fi
        if [ "$p_ref" = "RELEASE" ]; then
            if ! p_ref="$(xlnx_tag_for_release "$release")"; then
                echo -e "${RED}[ERROR]${RESET} No u-boot-xlnx tag known for release '${release}'; pass --ref explicitly." >&2
                exit 1
            fi
        fi
    fi
    ref="${ref:-$p_ref}"
    defconfig="${defconfig:-$p_defconfig}"
    dt="${dt:-$p_dt}"
    cross="${cross:-$p_cross}"
    if [ -z "$ref" ] || [ -z "$defconfig" ]; then
        echo -e "${RED}[ERROR]${RESET} Need --board <preset> or --ref + --defconfig." >&2
        exit 1
    fi
    if [ -z "$cross" ]; then
        case "$defconfig" in *zynqmp*|*versal*) cross="aarch64-linux-gnu-" ;; *) cross="arm-linux-gnueabihf-" ;; esac
    fi
    [ "$dt" = "-" ] && dt=""
    jobs="${jobs:-$(nproc 2>/dev/null || echo 4)}"

    echo -e "${BOLD}${GREEN}u-boot-xlnx build${RESET}"
    echo "  Board:         ${board:-(explicit)}"
    echo "  Ref:           ${ref}"
    echo "  Defconfig:     ${defconfig}"
    echo "  DEVICE_TREE:   ${dt:-(defconfig default)}"
    echo "  CROSS_COMPILE: ${cross}"
    echo "  Output:        ${UBOOT_DIR}/u-boot.elf"

    local dt_arg=""
    [ -n "$dt" ] && dt_arg="DEVICE_TREE=${dt}"
    if [ "$dry_run" = "true" ]; then
        echo -e "\n${YELLOW}[DRY-RUN] Commands that would be executed:${RESET}"
        echo "1) git -C \"${UBOOT_DIR}\" checkout ${ref}"
        echo "2) make -C \"${UBOOT_DIR}\" ${defconfig}"
        echo "3) make -C \"${UBOOT_DIR}\" -j${jobs} CROSS_COMPILE=${cross} ${dt_arg}"
        echo "4) make -C \"${UBOOT_DIR}\" CROSS_COMPILE=${cross} ${dt_arg} u-boot.elf"
        return 0
    fi

    if ! command -v "${cross}gcc" >/dev/null 2>&1; then
        echo -e "${RED}[ERROR]${RESET} ${cross}gcc not found. Install gcc-arm-linux-gnueabihf / gcc-aarch64-linux-gnu (see os-dependencies.yml)." >&2
        exit 1
    fi
    ensure_ref "$ref"
    set -e
    make -C "$UBOOT_DIR" distclean >/dev/null 2>&1 || true
    # shellcheck disable=SC2086
    make -C "$UBOOT_DIR" "$defconfig" CROSS_COMPILE="$cross" $dt_arg
    # shellcheck disable=SC2086
    make -C "$UBOOT_DIR" -j"$jobs" CROSS_COMPILE="$cross" $dt_arg
    # shellcheck disable=SC2086
    make -C "$UBOOT_DIR" CROSS_COMPILE="$cross" $dt_arg u-boot.elf
    echo -e "\n${BOLD}${GREEN}[SUCCESS]${RESET} ${UBOOT_DIR}/u-boot.elf"
}

main "$@"
