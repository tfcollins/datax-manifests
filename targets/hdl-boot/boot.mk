# ==============================================================================
# hdl-boot: build u-boot.elf and bl31.elf from source for the selected design
# ==============================================================================
# Both derive their board/arch/ref from HDL_PROJECT, HDL_BOARD and HDL_RELEASE
# unless UBOOT_BOARD / ATF_PLAT are set explicitly. Called from the generated
# Makefile's u-boot-xlnx / arm-trusted-firmware targets, which sdk-build
# depends on.

.PHONY: boot-uboot boot-atf boot-dry-run boot-clean

boot-uboot:
	@bash scripts/build-uboot.sh --board "$(UBOOT_BOARD)" --release "$(HDL_RELEASE)" --jobs "$$(nproc)" \
		--hdl-project "$(HDL_PROJECT)" --hdl-board "$(HDL_BOARD)" \
		$(if $(UBOOT_REF),--ref "$(UBOOT_REF)") $(if $(UBOOT_DEFCONFIG),--defconfig "$(UBOOT_DEFCONFIG)") \
		$(if $(UBOOT_DEVICE_TREE),--device-tree "$(UBOOT_DEVICE_TREE)")

# Zynq-7000 designs have no BL31: resolve the platform first and skip if none.
boot-atf:
	@plat="$(ATF_PLAT)"; if [ "$$plat" = auto ]; then plat="$$(bash scripts/build-hdl.sh --release "$(HDL_RELEASE)" --project "$(HDL_PROJECT)" --board "$(HDL_BOARD)" --boot-arch)"; fi; \
	case "$$plat" in \
	  zynqmp|versal) bash scripts/build-atf.sh --plat "$$plat" --release "$(HDL_RELEASE)" --console "$(ATF_CONSOLE)" --jobs "$$(nproc)" $(if $(ATF_REF),--ref "$(ATF_REF)") ;; \
	  zynq) echo "ATF: not needed for a Zynq-7000 design ($(HDL_PROJECT)/$(HDL_BOARD))" ;; \
	  *) echo "ATF: cannot determine boot architecture for $(HDL_PROJECT)/$(HDL_BOARD); set ATF_PLAT=zynqmp|versal" >&2; exit 1 ;; \
	esac

boot-dry-run:
	@bash scripts/build-uboot.sh --board "$(UBOOT_BOARD)" --release "$(HDL_RELEASE)" --hdl-project "$(HDL_PROJECT)" --hdl-board "$(HDL_BOARD)" --dry-run
	@plat="$(ATF_PLAT)"; if [ "$$plat" = auto ]; then plat="$$(bash scripts/build-hdl.sh --release "$(HDL_RELEASE)" --project "$(HDL_PROJECT)" --board "$(HDL_BOARD)" --boot-arch)"; fi; \
	[ "$$plat" = zynq ] && echo "ATF: not needed (zynq)" || bash scripts/build-atf.sh --plat "$$plat" --release "$(HDL_RELEASE)" --dry-run

boot-clean:
	@bash scripts/build-uboot.sh --clean
	@bash scripts/build-atf.sh --clean
