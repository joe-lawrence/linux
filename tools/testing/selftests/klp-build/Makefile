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
	@printf "  %-32s - %s\n" "runtime_tests" "Run runtime tests (auto-detects vng profile for VM mode)"
	@printf "  %-32s - %s\n" "report" "Write artifacts/report.txt (profile x test matrix, staggered header)"
	@printf "  %-32s - %s\n" "clean" "Remove __pycache__, *-generated.patch, and artifacts under selftest"

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

# runtime_tests: automatically detect virtme-ng profile and use VM mode if found
runtime_tests:
	@VNG_FLAG=""; \
	for profile_dir in "$(SELFTEST_DIR)/artifacts/"*/; do \
		if [ -d "$$profile_dir" ] && [ -f "$$profile_dir/profile" ]; then \
			profile_name=$$(cat "$$profile_dir/profile" 2>/dev/null); \
			case "$$profile_name" in \
				*virtme-ng*) \
					VNG_FLAG="--vng"; \
					break; \
					;; \
			esac; \
		fi; \
	done; \
	cd "$(KERNEL_SRC)" && python3 "$(SELFTEST_DIR)/run_runtime_tests.py" $$VNG_FLAG

# report: write summary matrix from artifacts/ (profiles x tests, staggered header)
report:
	@python3 "$(SELFTEST_DIR)/report.py"

clean:
	@find "$(SELFTEST_DIR)" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	@find "$(SELFTEST_DIR)/tests" -type f -name '*-generated.patch' -delete 2>/dev/null; true
	@rm -rf "$(SELFTEST_DIR)/artifacts"

.PHONY: tests_config build_tests build_tests_quick runtime_tests report clean help
