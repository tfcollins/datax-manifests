# ==============================================================================
# Helper targets for ADI HDL guided build flow and inspection
# ==============================================================================
# All targets honour HDL_RELEASE / VIVADO, e.g.:
#   make list-combos HDL_RELEASE=hdl_2023_r2
#   make check-tools HDL_RELEASE=hdl_2023_r2 VIVADO=/opt/Xilinx/2023.2/Vivado

HDL_SCRIPT_ARGS = --release "$(HDL_RELEASE)" --vivado "$(VIVADO)"

.PHONY: guide list-combos list-projects list-boards list-tools check-tools list-prebuilts download-prebuilt \
	config-json list-combos-json list-projects-json list-boards-json list-tools-json check-tools-json list-prebuilts-json

guide:
	@HDL_RELEASE="$(HDL_RELEASE)" VIVADO="$(VIVADO)" bash scripts/build-hdl.sh --interactive

list-combos:
	@bash scripts/build-hdl.sh $(HDL_SCRIPT_ARGS) --list

list-combos-json:
	@bash scripts/build-hdl.sh $(HDL_SCRIPT_ARGS) --list --json

list-projects:
	@bash scripts/build-hdl.sh $(HDL_SCRIPT_ARGS) --list-projects

list-projects-json:
	@bash scripts/build-hdl.sh $(HDL_SCRIPT_ARGS) --list-projects --json

list-boards:
	@bash scripts/build-hdl.sh $(HDL_SCRIPT_ARGS) --list-boards $(HDL_PROJECT)

list-boards-json:
	@bash scripts/build-hdl.sh $(HDL_SCRIPT_ARGS) --list-boards $(HDL_PROJECT) --json

list-tools:
	@bash scripts/build-hdl.sh $(HDL_SCRIPT_ARGS) --list-tools

list-tools-json:
	@bash scripts/build-hdl.sh $(HDL_SCRIPT_ARGS) --list-tools --json

check-tools:
	@bash scripts/build-hdl.sh $(HDL_SCRIPT_ARGS) --check-tools

check-tools-json:
	@bash scripts/build-hdl.sh $(HDL_SCRIPT_ARGS) --check-tools --json

HDL_PREBUILT_PY = $(if $(wildcard scripts/hdl-prebuilt.py),scripts/hdl-prebuilt.py,$(dir $(lastword $(MAKEFILE_LIST)))hdl-prebuilt.py)

list-prebuilts:
	@python3 $(HDL_PREBUILT_PY) --list

list-prebuilts-json:
	@python3 $(HDL_PREBUILT_PY) --list --json

config-json:
	@bash scripts/build-hdl.sh $(HDL_SCRIPT_ARGS) --project "$(HDL_PROJECT)" $(if $(HDL_BOARD),--board "$(HDL_BOARD)") \
		--jobs "$(MAKE_JOBS)" --dir-name "$(DIR_NAME)" --boot-bin "$(BUILD_BOOT_BIN)" \
		--boot-bin-uboot "$(BOOT_BIN_UBOOT)" --boot-bin-atf "$(BOOT_BIN_ATF)" \
		--hdl-bitstream "$(HDL_BITSTREAM)" --dry-run --json

download-prebuilt:
	@python3 $(HDL_PREBUILT_PY) --extract --project "$(HDL_PROJECT)" $(if $(HDL_BOARD),--board "$(HDL_BOARD)") --output "$(DIR_NAME)"
