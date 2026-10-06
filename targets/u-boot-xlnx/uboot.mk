# ==============================================================================
# u-boot-xlnx helper targets (included by the generated Makefile)
# ==============================================================================
# All variables come from sdk.yml and are overridable on the make command line:
#   make uboot-build UBOOT_BOARD=zed UBOOT_RELEASE=hdl_2023_r2
#   make uboot-build UBOOT_BOARD=jupiter_sdr
#   make uboot-build UBOOT_REF=my-branch UBOOT_DEFCONFIG=xilinx_zynqmp_virt_defconfig UBOOT_DEVICE_TREE=zynqmp-zcu102-rev1.0

UBOOT_SCRIPT_ARGS = --board "$(UBOOT_BOARD)" --release "$(UBOOT_RELEASE)" --jobs "$(UBOOT_JOBS)" \
	$(if $(UBOOT_REF),--ref "$(UBOOT_REF)") \
	$(if $(UBOOT_DEFCONFIG),--defconfig "$(UBOOT_DEFCONFIG)") \
	$(if $(UBOOT_DEVICE_TREE),--device-tree "$(UBOOT_DEVICE_TREE)") \
	$(if $(UBOOT_CROSS_COMPILE),--cross-compile "$(UBOOT_CROSS_COMPILE)") \
	$(if $(UBOOT_HDL_PROJECT),--hdl-project "$(UBOOT_HDL_PROJECT)") \
	$(if $(UBOOT_HDL_BOARD),--hdl-board "$(UBOOT_HDL_BOARD)")

.PHONY: uboot-build uboot-dry-run uboot-check-deps uboot-list uboot-clean

uboot-build:
	@bash scripts/build-uboot.sh $(UBOOT_SCRIPT_ARGS)

uboot-dry-run:
	@bash scripts/build-uboot.sh $(UBOOT_SCRIPT_ARGS) --dry-run

uboot-check-deps:
	@bash scripts/build-uboot.sh $(UBOOT_SCRIPT_ARGS) --check-deps

uboot-list:
	@bash scripts/build-uboot.sh --list

uboot-clean:
	@bash scripts/build-uboot.sh --clean
