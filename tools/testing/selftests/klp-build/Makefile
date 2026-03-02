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
	@echo ""
	@echo "Configuration:"
	@printf "  %-32s - %s\n" "tests_config" "No .config: defconfig + klp-build fragment; else merge fragment only"
	@printf "  %-32s - %s\n" "tests_config PROFILE=<n>" "Apply profile or chain (e.g. PROFILE=full-default, PROFILE=full-default+overlay-thin-lto)"
	@echo ""
	@echo "Build tests (TREE= required):"
	@printf "  %-32s - %s\n" "build_tests TREE=current" "Run current-tree tests (patch current kernel)"
	@printf "  %-32s - %s\n" "build_tests TREE=patched" "Run patched-tree tests (modify kernel first)"
	@printf "  %-32s - %s\n" "build_tests_quick" "Run quick current-tree tests only (always TREE=current)"
	@echo ""
	@echo "With profiles:"
	@printf "  %-32s - %s\n" "build_tests TREE=current PROFILE=a b" "Run current-tree tests for each profile"
	@printf "  %-32s - %s\n" "build_tests TREE=patched PROFILE=x" "Run patched-tree tests with profile x"
	@echo ""
	@echo "Advanced (run Python script directly):"
	@printf "  %-32s - %s\n" "./run_build_tests.py --help" "See all options including --test-type, --test, etc."
	@echo ""
	@echo "Runtime tests:"
	@printf "  %-32s - %s\n" "runtime_tests" "Load/verify livepatch modules using saved kernel"
	@echo ""
	@echo "Runtime tests auto-detect:"
	@echo "  - virtme-ng profile -> boots VM with saved kernel from build_tests"
	@echo "  - patched-tree tests -> applies base patches for module paths"
	@echo "  - No kernel rebuild: bzImage + modules are saved during build_tests"
	@echo ""
	@echo "Reporting:"
	@printf "  %-32s - %s\n" "report" "Write artifacts/report.{txt,html} (profile x test matrix)"
	@printf "  %-32s - %s\n" "clean" "Remove __pycache__, *-generated.patch, and artifacts/"
	@echo ""
	@echo "Test types (MUST choose one - cannot mix in same run):"
	@printf "  %-32s - %s\n" "TREE=current" "Patch current kernel (tests/current-tree/)"
	@printf "  %-32s - %s\n" "TREE=patched" "Modify kernel first (tests/patched-tree/)"
	@echo ""
	@echo "Why can't I mix test types?"
	@echo "  Patched-tree tests modify and rebuild the kernel, creating a different"
	@echo "  baseline than current-tree tests. Mixing them would corrupt artifacts and"
	@echo "  make runtime testing fail. Run each type separately."

# Stash path for .config when running build_tests with PROFILE=...
CONFIG_STASH := $(KERNEL_SRC)/.config.klp-build-stash

# build_tests: full suite. TREE= required (clean or patched). With PROFILE=blob1 blob2: stash .config, run each blob, restore.
build_tests:
	@if [ -z "$(TREE)" ]; then \
		echo "error: TREE= required (current or patched)"; \
		echo "  make build_tests TREE=current  # current-tree tests"; \
		echo "  make build_tests TREE=patched  # patched-tree tests"; \
		exit 1; \
	fi; \
	if [ "$(TREE)" != "current" ] && [ "$(TREE)" != "patched" ]; then \
		echo "error: TREE must be 'current' or 'patched', got '$(TREE)'"; \
		exit 1; \
	fi; \
	TEST_TYPE="$(TREE)-tree"; \
	if [ -z "$(PROFILE)" ]; then \
		cd "$(KERNEL_SRC)" && python3 "$(SELFTEST_DIR)/run_build_tests.py" --test-type "$$TEST_TYPE" || exit $$?; \
	else \
		rc=0; \
		if [ -r "$(KCONFIG_CONFIG)" ]; then cp "$(KCONFIG_CONFIG)" "$(CONFIG_STASH)"; fi; \
		for p in $(PROFILE); do \
			$(MAKE) -C "$(SELFTEST_DIR)" tests_config PROFILE="$$p" || { rc=$$?; echo "error: tests_config failed for $$p, skipping build_tests"; continue; }; \
			cd "$(KERNEL_SRC)" && python3 "$(SELFTEST_DIR)/run_build_tests.py" --profile "$$p" --test-type "$$TEST_TYPE" || rc=$$?; \
		done; \
		if [ -r "$(CONFIG_STASH)" ]; then mv "$(CONFIG_STASH)" "$(KCONFIG_CONFIG)"; fi; \
		exit $$rc; \
	fi

# build_tests_quick: current-tree quick tests only (current-tree/pass/quick + current-tree/fail/quick).
build_tests_quick:
	@if [ -z "$(PROFILE)" ]; then \
		cd "$(KERNEL_SRC)" && python3 "$(SELFTEST_DIR)/run_build_tests.py" --quick || exit $$?; \
	else \
		rc=0; \
		if [ -r "$(KCONFIG_CONFIG)" ]; then cp "$(KCONFIG_CONFIG)" "$(CONFIG_STASH)"; fi; \
		for p in $(PROFILE); do \
			$(MAKE) -C "$(SELFTEST_DIR)" tests_config PROFILE="$$p" || { rc=$$?; echo "error: tests_config failed for $$p, skipping build_tests"; continue; }; \
			cd "$(KERNEL_SRC)" && python3 "$(SELFTEST_DIR)/run_build_tests.py" --profile "$$p" --quick || rc=$$?; \
		done; \
		if [ -r "$(CONFIG_STASH)" ]; then mv "$(CONFIG_STASH)" "$(KCONFIG_CONFIG)"; fi; \
		exit $$rc; \
	fi

# runtime_tests: automatically detect virtme-ng profile and use VM mode if found.
# The kernel (bzImage + modules) was saved during build_tests -- no rebuild needed.
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

# report: write summary matrix from artifacts/ (report.txt + report.html with log links)
report:
	@python3 "$(SELFTEST_DIR)/report.py"
	@echo "Reports written to artifacts/report.txt and artifacts/report.html"

clean:
	@find "$(SELFTEST_DIR)" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	@find "$(SELFTEST_DIR)/tests" -type f -name '*-generated.patch' -delete 2>/dev/null; true
	@rm -rf "$(SELFTEST_DIR)/artifacts"

.PHONY: tests_config build_tests build_tests_quick runtime_tests report clean help
