# Offline discovery and guided selection, matching the HDL target conventions.
.PHONY: guide guide-help guide-dry-run list-combos list-dts

guide:
	@python3 scripts/guide-linux.py --interactive

guide-help:
	@python3 scripts/guide-linux.py --help

guide-dry-run:
	@python3 scripts/guide-linux.py --interactive --dry-run

list-combos:
	@python3 scripts/guide-linux.py --list

# Devicetrees from the boot-pairings CSV: all for KERNEL_PLATFORM, or those of
# one HDL project (make list-dts HDL_PROJECT=fmcomms2_zcu102).
list-dts:
	@python3 scripts/build-kernel.py --list-dts --release "$(KERNEL_RELEASE)" --platform "$(KERNEL_PLATFORM)" \
		$(if $(HDL_PROJECT),--hdl-project "$(HDL_PROJECT)")
