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
	@printf "  %-32s - %s\n" "build_tests" "Run full build test suite (no PROFILE: current .config; PROFILE=...: stash, run each, restore)"
	@printf "  %-32s - %s\n" "build_tests_quick" "Run quick tests only (pass/quick + fail/quick)"
	@printf "  %-32s - %s\n" "build_tests PROFILE=a b" "Run build_tests for each profile (e.g. full-default full-default+overlay-thin-lto)"
	@printf "  %-32s - %s\n" "clean" "Remove __pycache__ directories under selftest"

# Stash path for .config when running build_tests with PROFILE=...
CONFIG_STASH := $(KERNEL_SRC)/.config.klp-build-stash

# build_tests: full suite. With PROFILE=blob1 blob2: stash .config, run each blob, restore.
build_tests:
	@if [ -z "$(PROFILE)" ]; then \
		cd "$(KERNEL_SRC)" && python3 "$(SELFTEST_DIR)/run_build_tests.py" || exit $$?; \
	else \
		rc=0; \
		if [ -r "$(KCONFIG_CONFIG)" ]; then cp "$(KCONFIG_CONFIG)" "$(CONFIG_STASH)"; fi; \
		for p in $(PROFILE); do \
			$(MAKE) -C "$(SELFTEST_DIR)" tests_config PROFILE="$$p" || rc=$$?; \
			cd "$(KERNEL_SRC)" && python3 "$(SELFTEST_DIR)/run_build_tests.py" --profile "$$p" || rc=$$?; \
		done; \
		if [ -r "$(CONFIG_STASH)" ]; then mv "$(CONFIG_STASH)" "$(KCONFIG_CONFIG)"; fi; \
		exit $$rc; \
	fi

# build_tests_quick: pass/quick + fail/quick only.
build_tests_quick:
	@if [ -z "$(PROFILE)" ]; then \
		cd "$(KERNEL_SRC)" && python3 "$(SELFTEST_DIR)/run_build_tests.py" --quick || exit $$?; \
	else \
		rc=0; \
		if [ -r "$(KCONFIG_CONFIG)" ]; then cp "$(KCONFIG_CONFIG)" "$(CONFIG_STASH)"; fi; \
		for p in $(PROFILE); do \
			$(MAKE) -C "$(SELFTEST_DIR)" tests_config PROFILE="$$p" || rc=$$?; \
			cd "$(KERNEL_SRC)" && python3 "$(SELFTEST_DIR)/run_build_tests.py" --profile "$$p" --quick || rc=$$?; \
		done; \
		if [ -r "$(CONFIG_STASH)" ]; then mv "$(CONFIG_STASH)" "$(KCONFIG_CONFIG)"; fi; \
		exit $$rc; \
	fi

clean:
	@find "$(SELFTEST_DIR)" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true

.PHONY: tests_config build_tests build_tests_quick clean help
