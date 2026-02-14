# SPDX-License-Identifier: GPL-2.0
# klp-build selftests: config application targets.
# Run from kernel source root: make -C tools/testing/selftests/klp-build <target>

KERNEL_SRC := $(abspath $(CURDIR)/../../../..)
SELFTEST_DIR := $(CURDIR)
DEFAULT_FRAGMENT := $(SELFTEST_DIR)/profiles/0000-klp-build.fragment
MERGE_CONFIG := $(KERNEL_SRC)/scripts/kconfig/merge_config.sh
KCONFIG_CONFIG := $(KERNEL_SRC)/.config

# No PROFILE: no .config -> defconfig + overlay-klp-build; .config exists -> merge fragment only.
# PROFILE=... -> apply that profile or chain (script exits 77 for overlay-only when no .config).
tests_config:
	@if [ -z "$(PROFILE)" ]; then \
		if [ ! -r "$(KCONFIG_CONFIG)" ]; then \
			$(MAKE) -C "$(KERNEL_SRC)" defconfig; \
		fi; \
		if [ -r "$(DEFAULT_FRAGMENT)" ]; then \
			KCONFIG_CONFIG="$(KCONFIG_CONFIG)" "$(MERGE_CONFIG)" -m "$(KCONFIG_CONFIG)" "$(DEFAULT_FRAGMENT)" 1>/dev/null && \
			$(MAKE) -C "$(KERNEL_SRC)" olddefconfig; \
		else \
			$(MAKE) -C "$(KERNEL_SRC)" olddefconfig; \
		fi; \
	else \
		cd "$(KERNEL_SRC)" && python3 "$(SELFTEST_DIR)/apply_profile.py" "$(KERNEL_SRC)" "$(PROFILE)" || exit $$?; \
	fi

help:
	@echo "klp-build selftests targets:"
	@printf "  %-32s - %s\n" "tests_config" "No .config: defconfig + klp-build fragment; else merge fragment only"
	@printf "  %-32s - %s\n" "tests_config PROFILE=<n>" "Apply profile or chain (e.g. PROFILE=full-default, PROFILE=full-default+overlay-thin-lto)"

.PHONY: tests_config help
