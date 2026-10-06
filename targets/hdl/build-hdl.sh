#!/usr/bin/env bash
# ==============================================================================
# Analog Devices HDL Guided Build Flow
# ==============================================================================
# Guided build helper and board-tool matrix inspector for ADI HDL reference designs.
# Supports Xilinx Vivado, Intel Quartus, and Lattice Radiant.
#
# The HDL release (git branch/tag/sha of analogdevicesinc/hdl) is selected with
# --release / $HDL_RELEASE; the script checks out that release in the workspace
# hdl/ clone before inspecting or building, and picks the matching Vivado
# version unless --vivado / $VIVADO points at an explicit install.
# ==============================================================================

# Text formatting
BOLD="\033[1m"
GREEN="\033[32m"
BLUE="\033[34m"
CYAN="\033[36m"
YELLOW="\033[33m"
RED="\033[31m"
MAGENTA="\033[35m"
RESET="\033[0m"

HDL_UPSTREAM_URL="https://github.com/analogdevicesinc/hdl.git"
HDL_RELEASE_DEFAULT="hdl_2026_r1"

# Release selection and tool paths (CLI flags override these environment defaults)
HDL_RELEASE="${HDL_RELEASE:-$HDL_RELEASE_DEFAULT}"
VIVADO_OPT="${VIVADO:-auto}"
QUARTUS_DEFAULT="${QUARTUS:-/opt/intelFPGA_pro/23.4/quartus}"
LATTICE_DEFAULT="${LATTICE_RADIANT:-/usr/local/radiant}"
# Filled in by resolve_vivado() once the release is known
VIVADO_DEFAULT=""
VIVADO_VERSION=""

# Locate HDL root and workspace root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT=""
HDL_DIR=""

if [ -d "${SCRIPT_DIR}/../hdl/projects" ]; then
    WORKSPACE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
    HDL_DIR="${WORKSPACE_ROOT}/hdl"
elif [ -d "${PWD}/hdl/projects" ]; then
    WORKSPACE_ROOT="${PWD}"
    HDL_DIR="${WORKSPACE_ROOT}/hdl"
else
    # Search upwards
    curr="${PWD}"
    while [ "$curr" != "/" ]; do
        if [ -d "$curr/hdl/projects" ]; then
            WORKSPACE_ROOT="$curr"
            HDL_DIR="$curr/hdl"
            break
        fi
        curr="$(dirname "$curr")"
    done
fi

if [ -z "$HDL_DIR" ] || [ ! -d "$HDL_DIR/projects" ]; then
    echo -e "${RED}[ERROR]${RESET} Could not locate hdl/projects directory." >&2
    echo "Please run this script inside an initialized CIM workspace (after cim init) or repository root." >&2
    exit 1
fi

# Vivado version that each known HDL release was validated against.
vivado_version_for_release() {
    case "$1" in
        hdl_2023_r2) echo "2023.2" ;;
        hdl_2026_r1|main) echo "2025.1" ;;
        *) return 1 ;;
    esac
}

# Resolve VIVADO_DEFAULT / VIVADO_VERSION from --vivado / $VIVADO and the release.
# An explicit path is used verbatim; "auto" maps the release to a Vivado version
# and probes the usual install prefixes.  Returns 1 when auto-resolution is not
# possible for an unknown release.
resolve_vivado() {
    if [ -n "$VIVADO_OPT" ] && [ "$VIVADO_OPT" != "auto" ]; then
        VIVADO_DEFAULT="$VIVADO_OPT"
        VIVADO_VERSION="$(basename "$(dirname "$VIVADO_OPT")")"
        case "$VIVADO_VERSION" in [0-9]*.[0-9]*) ;; *) VIVADO_VERSION="$(basename "$VIVADO_OPT")" ;; esac
        return 0
    fi
    if ! VIVADO_VERSION="$(vivado_version_for_release "$HDL_RELEASE")"; then
        VIVADO_DEFAULT=""
        return 1
    fi
    local candidate
    for candidate in \
        "/opt/Xilinx/${VIVADO_VERSION}/Vivado" \
        "/opt/Xilinx/Vivado/${VIVADO_VERSION}" \
        "/tools/Xilinx/${VIVADO_VERSION}/Vivado" \
        "/tools/Xilinx/Vivado/${VIVADO_VERSION}"; do
        if [ -f "${candidate}/settings64.sh" ]; then
            VIVADO_DEFAULT="$candidate"
            return 0
        fi
    done
    VIVADO_DEFAULT="/opt/Xilinx/${VIVADO_VERSION}/Vivado"
    return 0
}

# Fail with guidance when Vivado cannot be auto-resolved for this release.
require_vivado() {
    if ! resolve_vivado; then
        echo -e "${RED}[ERROR]${RESET} No known Vivado version for HDL release '${HDL_RELEASE}'." >&2
        echo "Pass VIVADO=/path/to/Vivado (make VIVADO=... or --vivado ...) to select the install explicitly." >&2
        exit 1
    fi
}

# Return the commit a release name resolves to in the local clone, if any.
# Local branches win over origin/ so user commits on a release branch are never
# reset away; use "git -C hdl pull" to move a release forward.
local_release_commit() {
    local rel="$1" ref
    for ref in "refs/heads/${rel}" "refs/tags/${rel}" "refs/remotes/origin/${rel}" "${rel}"; do
        if git -C "$HDL_DIR" rev-parse --verify -q "${ref}^{commit}" 2>/dev/null; then
            return 0
        fi
    done
    return 1
}

# Make sure the workspace hdl/ clone is checked out at $HDL_RELEASE.
# Fetches the release from origin (or the upstream URL when origin is a mirror
# that lacks it) and refuses to switch away from a dirty worktree.
ensure_release() {
    local rel="$HDL_RELEASE"
    if [ ! -e "${HDL_DIR}/.git" ]; then
        echo -e "${YELLOW}[WARN]${RESET} ${HDL_DIR} is not a git checkout; cannot switch to release '${rel}'." >&2
        return 0
    fi
    local head want
    head="$(git -C "$HDL_DIR" rev-parse HEAD 2>/dev/null)" || head=""
    if want="$(local_release_commit "$rel")" && [ "$want" = "$head" ]; then
        return 0
    fi

    if [ -n "$(git -C "$HDL_DIR" status --porcelain --untracked-files=no)" ]; then
        echo -e "${RED}[ERROR]${RESET} hdl/ worktree is dirty; refusing to switch to release '${rel}'." >&2
        echo "Commit, stash or discard your changes in ${HDL_DIR} and retry." >&2
        exit 1
    fi

    echo -e "${CYAN}[INFO]${RESET} Switching hdl/ to release '${rel}'..."
    local fetched="false"
    if git -C "$HDL_DIR" fetch -q --depth 1 origin "$rel" 2>/dev/null \
        || git -C "$HDL_DIR" fetch -q origin "$rel" 2>/dev/null \
        || git -C "$HDL_DIR" fetch -q --depth 1 "$HDL_UPSTREAM_URL" "$rel" 2>/dev/null; then
        fetched="true"
    fi

    if [ "$fetched" = "true" ]; then
        git -C "$HDL_DIR" checkout -q --detach FETCH_HEAD || exit 1
        # Re-attach to a branch of the same name when the remote has one
        if git -C "$HDL_DIR" show-ref -q --verify "refs/remotes/origin/${rel}"; then
            git -C "$HDL_DIR" checkout -q -B "$rel" "origin/${rel}" || exit 1
        fi
    else
        # Not fetchable by name (e.g. a bare sha): deepen the clone and try locally
        git -C "$HDL_DIR" fetch -q --unshallow origin 2>/dev/null || git -C "$HDL_DIR" fetch -q origin 2>/dev/null || true
        if ! git -C "$HDL_DIR" checkout -q --detach "$rel" 2>/dev/null; then
            echo -e "${RED}[ERROR]${RESET} Could not fetch or check out HDL release '${rel}'." >&2
            echo "Check the name against ${HDL_UPSTREAM_URL} (branches: hdl_2023_r2, hdl_2026_r1, main)." >&2
            exit 1
        fi
    fi
    git -C "$HDL_DIR" submodule update -q --init --recursive 2>/dev/null || true
}

PROJECTS_DIR="${HDL_DIR}/projects"

# Helper function to identify required EDA tool for a project/board combo
get_required_tool() {
    local proj="$1"
    local board="$2"
    local mf="${PROJECTS_DIR}/${proj}/${board}/Makefile"

    if [ ! -f "$mf" ]; then
        echo "Unknown"
        return 1
    fi

    if grep -q "project-xilinx.mk" "$mf"; then
        echo "Vivado"
    elif grep -q "project-intel.mk" "$mf"; then
        echo "Quartus"
    elif grep -q "project-lattice.mk" "$mf"; then
        echo "Radiant"
    else
        echo "Vivado"
    fi
}

# Helper function to get tool version description
get_tool_desc() {
    local tool="$1"
    case "$tool" in
        Vivado)
            echo "Xilinx Vivado (Recommended: ${VIVADO_VERSION:-see --check-tools})"
            ;;
        Quartus)
            echo "Intel Quartus Prime (Pro / Standard)"
            ;;
        Radiant)
            echo "Lattice Radiant / Propel"
            ;;
        *)
            echo "$tool"
            ;;
    esac
}

# Get list of all available HDL projects (excluding common/scripts)
get_all_projects() {
    find "${PROJECTS_DIR}" -mindepth 1 -maxdepth 1 -type d ! -name "common" ! -name "scripts" -exec basename {} \; | sort
}

# Get list of supported boards for a given project
get_project_boards() {
    local proj="$1"
    if [ ! -d "${PROJECTS_DIR}/${proj}" ]; then
        return 1
    fi
    find "${PROJECTS_DIR}/${proj}" -mindepth 1 -maxdepth 1 -type d ! -name "common" ! -name "doc" | while read -r board_dir; do
        if [ -f "${board_dir}/Makefile" ]; then
            basename "${board_dir}"
        fi
    done | sort
}

# Check if a specific project and board combination exists
is_valid_combo() {
    local proj="$1"
    local board="$2"
    [ -f "${PROJECTS_DIR}/${proj}/${board}/Makefile" ]
}

# Check tool availability in environment
check_eda_tool_status() {
    local tool="$1"
    local res=0
    case "$tool" in
        Vivado)
            if [ -n "${XILINX_VIVADO:-}" ] && [ -f "${XILINX_VIVADO}/settings64.sh" ]; then
                echo -e "${GREEN}Found (via \$XILINX_VIVADO: ${XILINX_VIVADO})${RESET}"
                return 0
            elif [ -f "${VIVADO_DEFAULT}/settings64.sh" ]; then
                echo -e "${GREEN}Found (at ${VIVADO_DEFAULT})${RESET}"
                return 0
            elif command -v vivado >/dev/null 2>&1; then
                local vpath
                vpath="$(command -v vivado)"
                echo -e "${GREEN}Found in PATH (${vpath})${RESET}"
                return 0
            else
                echo -e "${YELLOW}Not detected (${VIVADO_DEFAULT} or PATH)${RESET}"
                return 1
            fi
            ;;
        Quartus)
            if [ -n "${QUARTUS_ROOTDIR:-}" ]; then
                echo -e "${GREEN}Found (via \$QUARTUS_ROOTDIR: ${QUARTUS_ROOTDIR})${RESET}"
                return 0
            elif [ -d "${QUARTUS_DEFAULT}" ]; then
                echo -e "${GREEN}Found (at ${QUARTUS_DEFAULT})${RESET}"
                return 0
            elif command -v quartus_sh >/dev/null 2>&1; then
                local qpath
                qpath="$(command -v quartus_sh)"
                echo -e "${GREEN}Found in PATH (${qpath})${RESET}"
                return 0
            else
                echo -e "${YELLOW}Not detected in default paths (${QUARTUS_DEFAULT} or PATH)${RESET}"
                return 1
            fi
            ;;
        Radiant)
            if [ -d "${LATTICE_DEFAULT}" ]; then
                echo -e "${GREEN}Found (at ${LATTICE_DEFAULT})${RESET}"
                return 0
            elif command -v radiantc >/dev/null 2>&1; then
                local rpath
                rpath="$(command -v radiantc)"
                echo -e "${GREEN}Found in PATH (${rpath})${RESET}"
                return 0
            else
                echo -e "${YELLOW}Not detected in default paths (${LATTICE_DEFAULT} or PATH)${RESET}"
                return 1
            fi
            ;;
    esac
}

# Environment setup command generator for make/bash execution
get_tool_env_setup() {
    local tool="$1"
    case "$tool" in
        Vivado)
            if [ -n "${XILINX_VIVADO:-}" ] && [ -f "${XILINX_VIVADO}/settings64.sh" ]; then
                echo "source \"${XILINX_VIVADO}/settings64.sh\""
            elif [ -f "${VIVADO_DEFAULT}/settings64.sh" ]; then
                echo "source \"${VIVADO_DEFAULT}/settings64.sh\""
            else
                echo "source \"${VIVADO_DEFAULT}/settings64.sh\""
            fi
            ;;
        Quartus)
            if [ -n "${QUARTUS_ROOTDIR:-}" ] && [ -f "${QUARTUS_ROOTDIR}/nios2eds/nios2_command_shell.sh" ]; then
                echo "source \"${QUARTUS_ROOTDIR}/nios2eds/nios2_command_shell.sh\""
            elif [ -f "${QUARTUS_DEFAULT}/../nios2eds/nios2_command_shell.sh" ]; then
                echo "source \"${QUARTUS_DEFAULT}/../nios2eds/nios2_command_shell.sh\""
            elif [ -d "${QUARTUS_DEFAULT}/bin" ]; then
                echo "export PATH=\"${QUARTUS_DEFAULT}/bin:\$PATH\""
            else
                echo "export PATH=\"${QUARTUS_DEFAULT}/bin:\$PATH\""
            fi
            ;;
        Radiant)
            if [ -d "${LATTICE_DEFAULT}/bin/lin64" ]; then
                echo "export PATH=\"${LATTICE_DEFAULT}/bin/lin64:\$PATH\""
            else
                echo "export PATH=\"${LATTICE_DEFAULT}/bin/lin64:\$PATH\""
            fi
            ;;
    esac
}

# List all projects and their supported board combinations
cmd_list_all() {
    echo -e "${BOLD}${CYAN}================================================================================${RESET}"
    echo -e "${BOLD}${CYAN} Analog Devices HDL Design Combinations & Tool Requirements (${HDL_RELEASE})${RESET}"
    echo -e "${BOLD}${CYAN}================================================================================${RESET}"
    printf "%-26s | %-20s | %-12s\n" "PROJECT" "CARRIER BOARD" "EDA TOOL"
    echo "---------------------------+----------------------+-------------"

    local total_combos=0
    for proj in $(get_all_projects); do
        local boards
        boards=$(get_project_boards "$proj")
        for board in $boards; do
            local tool
            tool=$(get_required_tool "$proj" "$board")
            local color="$GREEN"
            if [ "$tool" = "Quartus" ]; then color="$CYAN"; fi
            if [ "$tool" = "Radiant" ]; then color="$MAGENTA"; fi
            printf "%-26s | %-20s | ${color}%-12s${RESET}\n" "$proj" "$board" "$tool"
            total_combos=$((total_combos + 1))
        done
    done

    echo "---------------------------+----------------------+-------------"
    echo -e "${BOLD}Total: ${total_combos} project-carrier board combinations available.${RESET}\n"
}

# List tool overview matrix
cmd_list_tools() {
    echo -e "${BOLD}${CYAN}================================================================================${RESET}"
    echo -e "${BOLD}${CYAN} EDA Tools & Supported Carrier Boards Matrix (${HDL_RELEASE})${RESET}"
    echo -e "${BOLD}${CYAN}================================================================================${RESET}"
    
    echo -e "\n${BOLD}${GREEN}[1] Xilinx / AMD Vivado (${VIVADO_VERSION:-unknown for ${HDL_RELEASE}})${RESET}"
    echo "    Environment Script: ${VIVADO_DEFAULT:-<set VIVADO>}/settings64.sh (override via \$VIVADO)"
    echo "    Supported Carrier Boards:"
    echo "      - Zynq-7000:  zed, zc702, zc706, coraz7s, adrv2crr_fmc, adrv2crr_fmcomms8, ccbob_cmos, ccbob_lvds, ccfmc_lvds"
    echo "      - Zynq UltraScale+ (ZynqMP): zcu102, k26, kv260"
    echo "      - Versal ACAP: vck190, vmk180, vpk180"
    echo "      - Kintex / Virtex / Artix: ac701, kc705, kcu105, vc709, vcu118"

    echo -e "\n${BOLD}${CYAN}[2] Intel Quartus Prime (Pro / Standard)${RESET}"
    echo "    Environment Path: /opt/intelFPGA_pro/23.4/quartus (override via \$QUARTUS or \$QUARTUS_ROOTDIR)"
    echo "    Supported Carrier Boards:"
    echo "      - Cyclone V SoC:  de10nano, c5soc"
    echo "      - Arria 10 SoC:   a10soc, a10gx"
    echo "      - Stratix 10 SoC: s10soc"
    echo "      - Agilex / FM87:  fm87"

    echo -e "\n${BOLD}${MAGENTA}[3] Lattice Radiant / Propel${RESET}"
    echo "    Environment Path: /usr/local/radiant (override via \$LATTICE_RADIANT)"
    echo "    Supported Carrier Boards:"
    echo "      - Lattice Certus-NX: lfcpnx"
    echo ""
}

# Check tool status
cmd_check_tools() {
    echo -e "${BOLD}${CYAN}Checking EDA Tool Installation Status (release: ${HDL_RELEASE}):${RESET}"
    if resolve_vivado; then
        echo -e "  - Vivado version:  ${VIVADO_VERSION} (${VIVADO_DEFAULT})"
    else
        echo -e "  - Vivado version:  ${RED}unknown for release '${HDL_RELEASE}'${RESET} - set VIVADO=/path/to/Vivado"
    fi
    echo -n "  - Xilinx Vivado:   "
    check_eda_tool_status "Vivado" || true
    echo -n "  - Intel Quartus:   "
    check_eda_tool_status "Quartus" || true
    echo -n "  - Lattice Radiant: "
    check_eda_tool_status "Radiant" || true
    echo ""
    [ -n "$VIVADO_DEFAULT" ]
}

# List boards for a single project
cmd_list_boards_for_project() {
    local proj="$1"
    if [ ! -d "${PROJECTS_DIR}/${proj}" ]; then
        echo -e "${RED}[ERROR]${RESET} Project \x27${proj}\x27 not found." >&2
        echo "Use --list-projects to see all available projects." >&2
        return 1
    fi

    echo -e "${BOLD}Supported carrier boards for project \x27${CYAN}${proj}${RESET}\x27:${RESET}"
    printf "%-20s | %-12s | %s\n" "BOARD" "EDA TOOL" "TOOL SPECIFICATION"
    echo "---------------------+--------------+----------------------------------"
    for board in $(get_project_boards "$proj"); do
        local tool
        tool=$(get_required_tool "$proj" "$board")
        local tdesc
        tdesc=$(get_tool_desc "$tool")
        printf "%-20s | %-12s | %s\n" "$board" "$tool" "$tdesc"
    done
    echo ""
}

# Interactive guided build wizard
run_interactive_wizard() {
    echo -e "${BOLD}${CYAN}================================================================================${RESET}"
    echo -e "${BOLD}${CYAN}           Analog Devices HDL Guided Build Wizard (${HDL_RELEASE})${RESET}"
    echo -e "${BOLD}${CYAN}================================================================================${RESET}"

    # Step 0: Release Selection
    echo -e "\n${BOLD}${YELLOW}[Step 0/5] Select HDL Release${RESET}"
    echo "Known releases: hdl_2023_r2 (Vivado 2023.2), hdl_2026_r1 (Vivado 2025.1), main."
    echo "Any other branch, tag or commit of analogdevicesinc/hdl is accepted (set VIVADO= for those)."
    read -r -p "HDL release [${HDL_RELEASE}] > " input_release
    input_release=$(echo "$input_release" | xargs)
    if [ -n "$input_release" ]; then
        HDL_RELEASE="$input_release"
    fi
    ensure_release
    resolve_vivado || true

    # Step 1: Project Selection
    echo -e "\n${BOLD}${YELLOW}[Step 1/5] Select HDL Project${RESET}"
    echo "Type a project name (e.g., fmcomms2, adrv9009, ad9081_fmca_ebz, cn0561),"
    echo "or type ? or list to view all available projects, or filter <term> to search:"

    local selected_project=""
    while [ -z "$selected_project" ]; do
        read -r -p "Enter HDL Project > " input_proj
        input_proj=$(echo "$input_proj" | xargs)

        if [ "$input_proj" = "list" ] || [ "$input_proj" = "?" ]; then
            echo -e "${BOLD}Available HDL Projects:${RESET}"
            get_all_projects | column -c 80
            echo ""
        elif [[ "$input_proj" =~ ^filter\ (.*) ]]; then
            local filter_term="${BASH_REMATCH[1]}"
            echo -e "${BOLD}Projects matching \x27${filter_term}\x27:${RESET}"
            get_all_projects | grep -i "$filter_term" | column -c 80 || echo "  (No matches found)"
            echo ""
        elif [ -n "$input_proj" ]; then
            if [ -d "${PROJECTS_DIR}/${input_proj}" ]; then
                selected_project="$input_proj"
            else
                echo -e "${RED}Project \x27${input_proj}\x27 does not exist.${RESET} Type list to view all or filter <term> to search."
            fi
        fi
    done

    # Step 2: Board Selection
    echo -e "\n${BOLD}${YELLOW}[Step 2/5] Select Carrier Board for \x27${selected_project}\x27${RESET}"
    local available_boards=()
    while IFS= read -r b; do
        if [ -n "$b" ]; then
            available_boards+=("$b")
        fi
    done < <(get_project_boards "$selected_project")

    if [ ${#available_boards[@]} -eq 0 ]; then
        echo -e "${RED}[ERROR]${RESET} No carrier boards found for project \x27${selected_project}\x27." >&2
        exit 1
    fi

    echo "Available carrier boards:"
    for i in "${!available_boards[@]}"; do
        local b="${available_boards[$i]}"
        local t
        t=$(get_required_tool "$selected_project" "$b")
        local tdesc
        tdesc=$(get_tool_desc "$t")
        printf "  [%d] %-18s (Tool: %s - %s)\n" "$((i + 1))" "$b" "$t" "$tdesc"
    done

    local selected_board=""
    while [ -z "$selected_board" ]; do
        read -r -p "Select carrier board [1-${#available_boards[@]} or board name] > " input_board
        input_board=$(echo "$input_board" | xargs)

        if [[ "$input_board" =~ ^[0-9]+$ ]] && [ "$input_board" -ge 1 ] && [ "$input_board" -le "${#available_boards[@]}" ]; then
            selected_board="${available_boards[$((input_board - 1))]}"
        elif [ -n "$input_board" ]; then
            for b in "${available_boards[@]}"; do
                if [ "$b" = "$input_board" ]; then
                    selected_board="$b"
                    break
                fi
            done
            if [ -z "$selected_board" ]; then
                echo -e "${RED}Invalid board selection \x27${input_board}\x27.${RESET}"
            fi
        fi
    done

    # Step 3: Tool Verification
    local required_tool
    required_tool=$(get_required_tool "$selected_project" "$selected_board")
    local tool_desc
    tool_desc=$(get_tool_desc "$required_tool")

    echo -e "\n${BOLD}${YELLOW}[Step 3/5] EDA Tool Environment Verification${RESET}"
    echo -e "Required Tool for ${selected_project}/${selected_board}: ${BOLD}${CYAN}${required_tool}${RESET} (${tool_desc})"
    echo -n "Status: "
    check_eda_tool_status "$required_tool"

    # Step 4: Build Options
    echo -e "\n${BOLD}${YELLOW}[Step 4/5] Configure Build Options${RESET}"

    local nproc_val
    nproc_val=$(nproc 2>/dev/null || echo 4)
    read -r -p "Parallel make jobs [-j${nproc_val}] > " input_jobs
    local make_jobs="-j${nproc_val}"
    if [ -n "$input_jobs" ]; then
        if [[ "$input_jobs" =~ ^[0-9]+$ ]]; then
            make_jobs="-j${input_jobs}"
        else
            make_jobs="$input_jobs"
        fi
    fi

    read -r -p "Build output directory name [build] > " input_dirname
    local dir_name="${input_dirname:-build}"

    local build_boot_bin="false"
    # Check if board is Zynq or ZynqMP
    case "$selected_board" in
        zed|zc702|zc706|coraz7s|adrv2crr_*|ccbob_*|ccfmc_*|zcu102|k26|kv260)
            read -r -p "Generate BOOT.BIN binary? [y/N] > " input_boot
            if [[ "$input_boot" =~ ^[Yy] ]]; then
                build_boot_bin="true"
            fi
            ;;
    esac

    # Step 5: Summary & Execution Confirmation
    echo -e "\n${BOLD}${YELLOW}[Step 5/5] Build Configuration Summary${RESET}"
    echo -e "--------------------------------------------------------------------------------"
    echo -e "  HDL Release:           ${BOLD}${GREEN}${HDL_RELEASE}${RESET}"
    echo -e "  Project:               ${BOLD}${GREEN}${selected_project}${RESET}"
    echo -e "  Carrier Board:         ${BOLD}${GREEN}${selected_board}${RESET}"
    echo -e "  Required Tool:         ${BOLD}${CYAN}${required_tool}${RESET} (${tool_desc})"
    echo -e "  Parallel Jobs:         ${BOLD}${make_jobs}${RESET}"
    echo -e "  Output Folder:         ${BOLD}${dir_name}${RESET}"
    echo -e "  Generate BOOT.BIN:     ${BOLD}${build_boot_bin}${RESET}"
    echo -e "--------------------------------------------------------------------------------"
    echo -e "Equivalent CIM / Make command:"
    echo -e "  ${CYAN}make HDL_RELEASE=${HDL_RELEASE} HDL_PROJECT=${selected_project} HDL_BOARD=${selected_board} DIR_NAME=${dir_name} MAKE_JOBS=\"${make_jobs}\" BUILD_BOOT_BIN=${build_boot_bin} sdk-build${RESET}"
    echo -e "--------------------------------------------------------------------------------"

    read -r -p "Start the build now? [Y/n] > " confirm
    if [[ "$confirm" =~ ^[Nn] ]]; then
        echo -e "\nBuild cancelled. You can run the command above whenever you are ready."
        return 0
    fi

    # Run build
    execute_build "$selected_project" "$selected_board" "$make_jobs" "$dir_name" "$build_boot_bin" "download" "false"
}

# Execute the actual build
execute_build() {
    local proj="$1"
    local board="$2"
    local make_jobs="$3"
    local dir_name="$4"
    local boot_bin_enabled="$5"
    local boot_bin_uboot="${6:-download}"
    local dry_run="${7:-false}"

    if ! is_valid_combo "$proj" "$board"; then
        echo -e "${RED}[ERROR]${RESET} Invalid project/board combination: \x27${proj}/${board}\x27" >&2
        if [ -d "${PROJECTS_DIR}/${proj}" ]; then
            echo -e "Available boards for project \x27${proj}\x27:"
            get_project_boards "$proj" | sed "s/^/  - /"
        fi
        exit 1
    fi

    local tool
    tool=$(get_required_tool "$proj" "$board")
    if [ "$tool" = "Vivado" ]; then require_vivado; fi
    local env_setup
    env_setup=$(get_tool_env_setup "$tool")

    local project_board_dir="${HDL_DIR}/projects/${proj}/${board}"

    echo -e "\n${BOLD}${GREEN}================================================================================${RESET}"
    echo -e "${BOLD}${GREEN} Building ADI HDL Design: ${proj} / ${board} [${tool}] (${HDL_RELEASE}) ${RESET}"
    echo -e "${BOLD}${GREEN}================================================================================${RESET}"
    echo -e "  HDL Release:       ${HDL_RELEASE}"
    echo -e "  Project Directory: ${project_board_dir}"
    echo -e "  Tool Setup:        ${env_setup}"
    echo -e "  Make Jobs:         ${make_jobs}"
    echo -e "  Output Folder:     ${dir_name}"

    if [ "$dry_run" = "true" ]; then
        echo -e "\n${YELLOW}[DRY-RUN] Commands that would be executed:${RESET}"
        echo "1) ${env_setup}"
        echo "2) make ${make_jobs} -C \"${project_board_dir}\" DIR_NAME=\"${dir_name}\""
        if [ "$boot_bin_enabled" = "true" ]; then
            echo "3) cd \"${project_board_dir}\" && bash \"${WORKSPACE_ROOT}/scripts/build_boot_bin.sh\" \"${dir_name}/${proj}_${board}.sdk/system_top.xsa\" \"${boot_bin_uboot}\""
        fi
        return 0
    fi

    # Build execution
    echo -e "\n${BOLD}Starting build...${RESET}\n"
    
    # Run build in a subshell with tool environment
    bash -c "
        set -e
        ${env_setup} 2>/dev/null || true
        MAKEOVERRIDES= make --no-print-directory ${make_jobs} -C \"${project_board_dir}\" DIR_NAME=\"${dir_name}\"
        if [ \"${boot_bin_enabled}\" = \"true\" ]; then
            if [ -f \"${WORKSPACE_ROOT}/scripts/build_boot_bin.sh\" ]; then
                echo -e \x27\n${BOLD}${CYAN}Generating BOOT.BIN...${RESET}\x27
                cd \"${project_board_dir}\"
                bash \"${WORKSPACE_ROOT}/scripts/build_boot_bin.sh\" \"${dir_name}/${proj}_${board}.sdk/system_top.xsa\" \"${boot_bin_uboot}\"
            fi
        fi
    "

    echo -e "\n${BOLD}${GREEN}[SUCCESS] HDL Build completed successfully for ${proj}/${board}!${RESET}\n"
}

# Clean a project/board build directory with the right tool environment
execute_clean() {
    local proj="$1"
    local board="$2"
    local dir_name="$3"
    local project_board_dir="${HDL_DIR}/projects/${proj}/${board}"

    if ! is_valid_combo "$proj" "$board"; then
        echo "Project/board ${proj}/${board} does not exist in release ${HDL_RELEASE}; nothing to clean."
        return 0
    fi
    local tool
    tool=$(get_required_tool "$proj" "$board")
    if [ "$tool" = "Vivado" ]; then require_vivado; fi
    local env_setup
    env_setup=$(get_tool_env_setup "$tool")
    bash -c "
        ${env_setup} 2>/dev/null || true
        MAKEOVERRIDES= make --no-print-directory -C \"${project_board_dir}\" DIR_NAME=\"${dir_name}\" clean
    "
}

# Print usage / help
show_help() {
    cat << EOF
Analog Devices HDL Guided Build Flow

Usage:
  $(basename "$0") [OPTIONS]

Interactive Mode:
  $(basename "$0")                    Launch interactive guided wizard (when in TTY)
  $(basename "$0") -i, --interactive  Force interactive guided wizard

Release / Tool Selection:
  -r, --release <ref>        HDL release to build from: branch, tag or commit of
                             analogdevicesinc/hdl (default: \$HDL_RELEASE or ${HDL_RELEASE_DEFAULT}).
                             The workspace hdl/ clone is switched to this ref first.
  --vivado <path|auto>       Vivado install dir (default: \$VIVADO or auto). "auto" picks
                             the version validated for the release: hdl_2023_r2 -> 2023.2,
                             hdl_2026_r1 / main -> 2025.1.

Direct Build Options:
  -p, --project <name>       HDL Project name (e.g. fmcomms2, adrv9009, cn0561)
  -b, --board <name>         Carrier board name (e.g. zcu102, zed, de10nano, a10soc)
  -j, --jobs <N>             Parallel make jobs (e.g. -j8, default: -j\$(nproc))
  -d, --dir-name <name>      Build output directory name (default: build)
  --boot-bin [true|false]    Generate BOOT.BIN binary for Zynq/ZynqMP designs
  --clean                    Run the project/board "make clean" instead of building
  --boot-bin-uboot <mode>    U-Boot binary source for BOOT.BIN (default: download)
  --dry-run                  Display resolved tool environment and make commands without executing

Inspection & Information Options:
  -l, --list                 List all 160+ project-carrier board combinations and required tools
  --list-projects            List all available HDL projects
  --list-boards <project>    List all supported carrier boards for a specific project
  --list-tools               List carrier boards and projects grouped by EDA tool (Vivado, Quartus, Radiant)
  --check-tools              Check presence of Vivado, Quartus, and Radiant in local environment
                             (exits non-zero if Vivado cannot be resolved for the release)
  -h, --help                 Show this help message

Examples:
  # Launch interactive wizard
  ./scripts/build-hdl.sh

  # List all supported project-board combinations
  ./scripts/build-hdl.sh --list

  # List combinations available in the hdl_2023_r2 release
  ./scripts/build-hdl.sh --release hdl_2023_r2 --list

  # List boards for fmcomms2
  ./scripts/build-hdl.sh --list-boards fmcomms2

  # Check if EDA tools are installed
  ./scripts/build-hdl.sh --check-tools

  # Build fmcomms2 for ZedBoard with Vivado and generate BOOT.BIN
  ./scripts/build-hdl.sh --project fmcomms2 --board zed --boot-bin

  # Build cn0561 for DE10-Nano with Intel Quartus
  ./scripts/build-hdl.sh --project cn0561 --board de10nano --jobs 8
EOF
}

# Parse CLI arguments
main() {
    local opt_proj=""
    local opt_board=""
    local opt_jobs="-j$(nproc 2>/dev/null || echo 4)"
    local opt_dirname="build"
    local opt_boot_bin="false"
    local opt_uboot="download"
    local opt_dry_run="false"
    local opt_interactive="false"
    local opt_clean="false"
    local opt_action=""
    local opt_action_arg=""

    if [ $# -eq 0 ]; then
        if [ -t 0 ]; then
            run_interactive_wizard
            return 0
        else
            show_help
            return 0
        fi
    fi

    while [ $# -gt 0 ]; do
        case "$1" in
            -i|--interactive)
                opt_interactive="true"
                shift
                ;;
            -r|--release)
                HDL_RELEASE="$2"
                shift 2
                ;;
            --vivado)
                VIVADO_OPT="$2"
                shift 2
                ;;
            -p|--project)
                opt_proj="$2"
                shift 2
                ;;
            -b|--board)
                opt_board="$2"
                shift 2
                ;;
            -j|--jobs)
                if [[ "$2" =~ ^[0-9]+$ ]]; then
                    opt_jobs="-j$2"
                else
                    opt_jobs="$2"
                fi
                shift 2
                ;;
            -d|--dir-name)
                opt_dirname="$2"
                shift 2
                ;;
            --boot-bin)
                case "${2:-}" in
                    true|false) opt_boot_bin="$2"; shift 2 ;;
                    *) opt_boot_bin="true"; shift ;;
                esac
                ;;
            --no-boot-bin)
                opt_boot_bin="false"
                shift
                ;;
            --boot-bin-uboot)
                opt_uboot="$2"
                shift 2
                ;;
            --dry-run)
                opt_dry_run="true"
                shift
                ;;
            --clean)
                opt_clean="true"
                shift
                ;;
            -l|--list)
                opt_action="list"
                shift
                ;;
            --list-projects)
                opt_action="list-projects"
                shift
                ;;
            --list-boards)
                if [ -z "${2:-}" ]; then
                    echo -e "${RED}[ERROR]${RESET} Missing project argument for --list-boards." >&2
                    echo "Usage: $(basename "$0") --list-boards <project_name>" >&2
                    exit 1
                fi
                opt_action="list-boards"
                opt_action_arg="$2"
                shift 2
                ;;
            --list-tools)
                opt_action="list-tools"
                shift
                ;;
            --check-tools)
                opt_action="check-tools"
                shift
                ;;
            -h|--help)
                show_help
                return 0
                ;;
            *)
                echo -e "${RED}[ERROR]${RESET} Unknown option: $1" >&2
                echo "Run $(basename "$0") --help for usage instructions." >&2
                exit 1
                ;;
        esac
    done

    if [ "$opt_interactive" = "true" ]; then
        run_interactive_wizard
        return 0
    fi

    # Every remaining action inspects or builds the selected release
    ensure_release
    resolve_vivado || true

    case "$opt_action" in
        list)
            cmd_list_all
            return 0
            ;;
        list-projects)
            echo -e "${BOLD}Available HDL Projects (${HDL_RELEASE}):${RESET}"
            get_all_projects | column -c 80
            return 0
            ;;
        list-boards)
            cmd_list_boards_for_project "$opt_action_arg"
            return $?
            ;;
        list-tools)
            cmd_list_tools
            return 0
            ;;
        check-tools)
            cmd_check_tools
            return $?
            ;;
    esac

    if [ -n "$opt_proj" ] && [ -n "$opt_board" ]; then
        if [ "$opt_clean" = "true" ]; then
            execute_clean "$opt_proj" "$opt_board" "$opt_dirname"
        else
            execute_build "$opt_proj" "$opt_board" "$opt_jobs" "$opt_dirname" "$opt_boot_bin" "$opt_uboot" "$opt_dry_run"
        fi
    elif [ -n "$opt_proj" ] && [ -z "$opt_board" ]; then
        cmd_list_boards_for_project "$opt_proj"
        echo -e "${YELLOW}[HINT]${RESET} Specify a carrier board with --board <board_name> to build."
    else
        echo -e "${RED}[ERROR]${RESET} Both --project and --board must be specified for non-interactive build." >&2
        echo "Run with --interactive or $(basename "$0") --help for options." >&2
        exit 1
    fi
}

main "$@"
