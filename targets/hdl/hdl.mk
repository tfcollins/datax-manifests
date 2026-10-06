# ==============================================================================
# Helper targets for ADI HDL guided build flow and inspection
# ==============================================================================
# All targets honour HDL_RELEASE / VIVADO, e.g.:
#   make list-combos HDL_RELEASE=hdl_2023_r2
#   make check-tools HDL_RELEASE=hdl_2023_r2 VIVADO=/opt/Xilinx/2023.2/Vivado

HDL_SCRIPT_ARGS = --release "$(HDL_RELEASE)" --vivado "$(VIVADO)"

.PHONY: guide list-combos list-projects list-boards list-tools check-tools

guide:
	@HDL_RELEASE="$(HDL_RELEASE)" VIVADO="$(VIVADO)" bash scripts/build-hdl.sh --interactive

list-combos:
	@bash scripts/build-hdl.sh $(HDL_SCRIPT_ARGS) --list

list-projects:
	@bash scripts/build-hdl.sh $(HDL_SCRIPT_ARGS) --list-projects

list-boards:
	@bash scripts/build-hdl.sh $(HDL_SCRIPT_ARGS) --list-boards $(HDL_PROJECT)

list-tools:
	@bash scripts/build-hdl.sh $(HDL_SCRIPT_ARGS) --list-tools

check-tools:
	@bash scripts/build-hdl.sh $(HDL_SCRIPT_ARGS) --check-tools
