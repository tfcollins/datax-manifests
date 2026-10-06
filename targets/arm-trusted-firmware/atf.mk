# ==============================================================================
# arm-trusted-firmware helper targets (included by the generated Makefile)
# ==============================================================================
#   make atf-build ATF_PLAT=zynqmp ATF_RELEASE=hdl_2023_r2
#   make atf-build ATF_REF=xilinx-v2025.2

ATF_SCRIPT_ARGS = --plat "$(ATF_PLAT)" --release "$(ATF_RELEASE)" --console "$(ATF_CONSOLE)" --jobs "$(ATF_JOBS)" \
	$(if $(ATF_REF),--ref "$(ATF_REF)")

.PHONY: atf-build atf-dry-run atf-clean

atf-build:
	@bash scripts/build-atf.sh $(ATF_SCRIPT_ARGS)

atf-dry-run:
	@bash scripts/build-atf.sh $(ATF_SCRIPT_ARGS) --dry-run

atf-clean:
	@bash scripts/build-atf.sh --clean
