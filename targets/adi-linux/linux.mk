# Offline discovery and guided selection, matching the HDL target conventions.
.PHONY: guide guide-help guide-dry-run list-combos

guide:
	@python3 scripts/guide-linux.py --interactive

guide-help:
	@python3 scripts/guide-linux.py --help

guide-dry-run:
	@python3 scripts/guide-linux.py --interactive --dry-run

list-combos:
	@python3 scripts/guide-linux.py --list
