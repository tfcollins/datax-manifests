# ==============================================================================
# hdl-boot: build u-boot.elf and bl31.elf from source for the selected design
# ==============================================================================
# Both derive their board/arch/ref from HDL_PROJECT, HDL_BOARD and HDL_RELEASE
# unless UBOOT_BOARD / ATF_PLAT are set explicitly. Called from the generated
# Makefile's u-boot-xlnx / arm-trusted-firmware targets, which sdk-build
# depends on.

.PHONY: boot-uboot boot-atf boot-dry-run boot-clean boot-config-json

# Overrides shared by the real recipes, boot-dry-run and boot-config-json, so
# the exported plan is exactly what boot-uboot / boot-atf would build.
BOOT_UBOOT_ARGS = --board "$(UBOOT_BOARD)" --release "$(HDL_RELEASE)" \
	--hdl-project "$(HDL_PROJECT)" $(if $(HDL_BOARD),--hdl-board "$(HDL_BOARD)") \
	$(if $(UBOOT_REF),--ref "$(UBOOT_REF)") $(if $(UBOOT_DEFCONFIG),--defconfig "$(UBOOT_DEFCONFIG)") \
	$(if $(UBOOT_DEVICE_TREE),--device-tree "$(UBOOT_DEVICE_TREE)")
BOOT_ATF_ARGS = --release "$(HDL_RELEASE)" --console "$(ATF_CONSOLE)" $(if $(ATF_REF),--ref "$(ATF_REF)")
# Design boot architecture (zynq/zynqmp/versal) unless ATF_PLAT forces one;
# "none" when the design cannot boot from a BOOT.BIN. --boot-arch itself
# prints "none" and exits 1 in that case, so never append a second "none".
BOOT_PLAT_SH = plat="$(ATF_PLAT)"; if [ "$$plat" = auto ]; then \
	plat="$$(bash scripts/build-hdl.sh --release "$(HDL_RELEASE)" --project "$(HDL_PROJECT)" $(if $(HDL_BOARD),--board "$(HDL_BOARD)") --boot-arch)" || plat=none; fi

# Nothing to build when no BOOT.BIN is requested or the prebuilt download is
# selected (make sdk-build BUILD_BOOT_BIN=false / BOOT_BIN_UBOOT=download).
boot-uboot:
	@if [ "$(BUILD_BOOT_BIN)" != true ] || [ "$(BOOT_BIN_UBOOT)" = download ]; then \
	  echo "u-boot: skipped (BUILD_BOOT_BIN=$(BUILD_BOOT_BIN), BOOT_BIN_UBOOT=$(BOOT_BIN_UBOOT))"; exit 0; fi; \
	bash scripts/build-uboot.sh $(BOOT_UBOOT_ARGS) --jobs "$$(nproc)"

# Zynq-7000 designs have no BL31: resolve the platform first and skip if none.
boot-atf:
	@if [ "$(BUILD_BOOT_BIN)" != true ] || [ "$(BOOT_BIN_ATF)" = download ]; then \
	  echo "ATF: skipped (BUILD_BOOT_BIN=$(BUILD_BOOT_BIN), BOOT_BIN_ATF=$(BOOT_BIN_ATF))"; exit 0; fi; \
	$(BOOT_PLAT_SH); \
	case "$$plat" in \
	  zynqmp|versal) bash scripts/build-atf.sh --plat "$$plat" $(BOOT_ATF_ARGS) --jobs "$$(nproc)" ;; \
	  zynq) echo "ATF: not needed for a Zynq-7000 design ($(HDL_PROJECT)/$(HDL_BOARD))" ;; \
	  *) echo "ATF: cannot determine boot architecture for $(HDL_PROJECT)/$(HDL_BOARD); set ATF_PLAT=zynqmp|versal" >&2; exit 1 ;; \
	esac

boot-dry-run:
	@bash scripts/build-uboot.sh $(BOOT_UBOOT_ARGS) --dry-run
	@$(BOOT_PLAT_SH); \
	case "$$plat" in \
	  zynqmp|versal) bash scripts/build-atf.sh --plat "$$plat" $(BOOT_ATF_ARGS) --dry-run ;; \
	  zynq) echo "ATF: not needed (zynq)" ;; \
	  *) echo "ATF: cannot determine boot architecture for $(HDL_PROJECT)/$(HDL_BOARD); set ATF_PLAT=zynqmp|versal" >&2; exit 1 ;; \
	esac

boot-clean:
	@bash scripts/build-uboot.sh --clean
	@bash scripts/build-atf.sh --clean

# JSON plan for both components. A design that cannot boot from a BOOT.BIN
# reports boot_arch "none" with null uboot/atf; a u-boot that cannot be
# resolved (no preset, no UBOOT_REF/UBOOT_DEFCONFIG) is null plus a message on
# stderr, so stdout is always one JSON document.
boot-config-json:
	@$(BOOT_PLAT_SH); \
	uboot=""; atf=""; \
	if [ "$$plat" != none ]; then \
	  uboot="$$(bash scripts/build-uboot.sh $(BOOT_UBOOT_ARGS) --dry-run --json)" || { uboot=""; \
	    echo "boot-config-json: u-boot could not be resolved for $(HDL_PROJECT)$(if $(HDL_BOARD),/$(HDL_BOARD)); set UBOOT_BOARD or UBOOT_REF + UBOOT_DEFCONFIG" >&2; }; \
	  case "$$plat" in \
	    zynqmp|versal) atf="$$(bash scripts/build-atf.sh --plat "$$plat" $(BOOT_ATF_ARGS) --dry-run --json)" || { atf=""; \
	      echo "boot-config-json: ATF could not be resolved for $$plat; set ATF_REF" >&2; } ;; \
	  esac; \
	fi; \
	python3 -c 'import json, sys; load = lambda s: json.loads(s) if s.strip() else None; print(json.dumps({"target": "hdl-boot", "boot_arch": sys.argv[3], "uboot": load(sys.argv[1]), "atf": load(sys.argv[2])}, indent=2))' \
	  "$$uboot" "$$atf" "$$plat"
