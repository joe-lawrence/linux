# klp-build selftests: config profiles and tests (end-user summary)

## 0. Intro

This branch is broken into three parts: **kernel configuration**, **klp-build .patch build testing**, and **livepatch runtime verification**. Each part feeds the next—the chosen kernel config and toolchain affect what gets built, and the built artifacts drive what can be verified at runtime.

Before diving in, it helps to name the thing that ties these steps together. A test **profile** is the combination of kernel config, toolchain, and (when relevant) runtime environment. The profile affects all subsequent steps: build and runtime tests run in the context of that profile. That makes the profile a natural way to categorize testing—different profiles exercise different areas of klp-build, so some build or runtime tests that succeed under one profile may fail under another. The sections below cover each of the three parts in turn.

---

## 1. Kernel configuration

The harness supports several ways to arrive at a `.config` (and thus at a profile). Three main use cases:

### 1. Bring your own .config

The simplest case is for the developer to bring their own `.config`. The test harness does not participate in kernel configuration; it just uses whatever `.config` is present. Subsequent steps (build tests, runtime tests) gracefully pick up and run with that config. The testing profile is **implied** from this `.config`—e.g. the harness may match the current `.config` to a known profile in `artifacts/` for labeling, or treat it as a generic "current" profile. If you only merge the default klp-build fragment on top of your existing `.config` (e.g. via `tests_config` with no `PROFILE`), that still counts as BYO: your base config is unchanged except for the added fragment.

### 2. Harness-provided full profiles

The test harness provides its own set of **fully-defined profiles**. These might be a distro-style configuration, a profile from a user bug report, or a minimal defconfig plus klp-build options. Each is a complete recipe (e.g. `config_base` such as `make defconfig` or `virtme-ng --kconfig`, plus optional fragments). Applying such a profile creates or overwrites `.config`. Examples: `full-default`, `full-virtme-ng`. Profiles live under `tools/testing/selftests/klp-build/profiles/<name>/` with a `config.yaml` file; type is inferred from the directory name (`full-*` vs `overlay-*`).

### 3. Config fragment overlays

**Overlay** profiles allow layering several kernel profile "features" on top of one another—e.g. thin-LTO, debug options, or an extra fragment. They have only `config_apply` (no `config_base`); fragments are merged additively on top of an existing `.config` or on top of the result of a previous profile in a chain. You can build a chain with `PROFILE=prof1+prof2+prof3...`; profiles are applied in order. A profile may specify a **required toolchain** and/or **runtime**. The first profile in the chain that sets a given requirement "wins," and that choice is enforced through the rest of the configuration merging—so you cannot combine, for example, an LLVM-required profile and a GCC-required profile in the same chain. After merging and `make olddefconfig`, a **final .config verification** step ensures that each overlayed profile's specified options are still present in the resulting `.config`; only the options from the overlay fragments are checked (the base config is not verified).

#### Example: thin-lto overlay

The `overlay-thin-lto` profile layers the klp-build fragment and a thin LTO fragment on top of a base config and sets the toolchain to clang/ld.lld:

```yaml
# profiles/overlay-thin-lto/config.yaml
name: overlay-thin-lto
description: Clang Thin-LTO overlay

config_apply:
  - ../0000-klp-build.fragment
  - 0001-thin-lto.fragment

toolchain:
  compiler: clang
  linker: ld.lld
  assembler: clang

runtime: true
```

**Usage 1** — merge thin-lto on top of your current .config:

```bash
# Merge thin-lto options on top of current .config
make -C tools/testing/selftests/klp-build tests_config \
    PROFILE=overlay-thin-lto
```

**Usage 2** — full base plus overlay:

```bash
# Create a profile from the full virtme-ng config, then overlay
# the thin-lto options on top.
make -C tools/testing/selftests/klp-build tests_config \
    PROFILE=full-virtme-ng+overlay-thin-lto
```

Chaining: `PROFILE=full-default+overlay-thin-lto` applies the full defconfig-based profile first, then the thin-lto overlay; the overlay's toolchain is used for the whole chain. Overlay-only with no existing `.config` (e.g. `PROFILE=overlay-thin-lto` and no `.config`) causes the apply step to exit 77 (kselftest skip).

---

## 2. klp-build .patch build testing

Build tests run `klp-build` on test patches (and optionally verify the result) in the context of the current profile. Because different profiles exercise different areas of klp-build, a test that passes under one profile may fail under another—or be skipped if it doesn't apply to that profile. Tests live under `tools/testing/selftests/klp-build/tests/` and are discovered by outcome and speed.

### Require certain config/profile

- Each test can declare in `expected.py`: `CONFIG_PROFILES`, `REQUIRED_CONFIG`, `SUPPORTED_COMPILERS`, `SUPPORTED_ARCHES`.
- The runner filters with `test_belongs_to_profile()`: a test runs only when the current profile (or implied profile), config, compiler, and arch match its requirements—or when it has no requirements.

### Verification checks

- After a build, the test's `run_verify()` (from `expected.py`) can run checks. Results are recorded and written to the **BUILD VERIFICATION** section of `build-test.log` (each check as `OK` or `FAIL`).

### Pass vs. fail

- **Pass tests** (`tests/<tree>/pass/...`): klp-build is expected to succeed (exit 0).
- **Fail tests** (`tests/<tree>/fail/...`): klp-build is expected to fail (non-zero exit).

### Short vs. long

- Current-tree tests are organized as `pass/quick`, `pass/long`, `fail/quick`, `fail/long`. Patched-tree tests are organized as `pass/` (no quick/long split).
- **Quick:** `build_tests_quick` runs only current-tree tests under `*/quick`.
- **Long:** full `build_tests` runs both quick and long.

### Generated vs. static patches

- **Static patches:** The test directory contains one or more `*.patch` files; they are used in alphanumeric order.
- **Generated patches:** The test's `expected.py` defines `generate_patches(test_dir, kernel_root, out_path)` (or the test provides a script such as `generate.sh`). The runner calls it and writes `<test_name>-generated.patch`; that patch is then used for the run. `make clean` removes all `*-generated.patch` under `tests/`.

### Example build-test.log

The log file is written to `artifacts/<profile>/<tree>/<test_name>/build-test.log`. Example:

```
======================================================================
BUILD LOG: pass/quick/cmdline-string
======================================================================
Verdict:    pass
Exit code:  0

Kernel:     6.19.0+
Toolchain:
  Compiler:   gcc (GCC) 15.2.1 20260123 (Red Hat 15.2.1-7)
  Linker:     GNU ld version 2.45.1-4.fc43
  Assembler:  GNU assembler version 2.45.1-4.fc43

======================================================================
FULL BUILD OUTPUT
======================================================================

--- klp-build stdout ---
Validating patch(es)
Building original kernel
Copying original object files
Fixing patch(es)
Building patched kernel
Copying patched object files
Diffing objects
vmlinux.o: changed function: cmdline_proc_show
Building patch module: livepatch-cmdline-string.ko
SUCCESS

--- klp-build stderr ---
(empty)

--- diff.log ---
vmlinux.o: changed function: cmdline_proc_show


======================================================================
BUILD VERIFICATION
======================================================================

klp-build exit code is 0
Module exists: livepatch-cmdline-string.ko
verify_diff_log_contains('changed function: cmdline_proc_show'): OK

ELF Analysis:
klp_object[0]:
  .name = NULL (vmlinux)
VERIFIED: klp_object.name = NULL (vmlinux)
    klp_func[0]:
      .old_name = "cmdline_proc_show"  [-> .rodata+0x75]
      .new_func -> cmdline_proc_show
      .old_sympos = 0
    VERIFIED: klp_func.old_name = 'cmdline_proc_show'
    VERIFIED: klp_func.new_func -> cmdline_proc_show

======================================================================
TEST PATCH(ES)
======================================================================

--- Patch: cmdline-string.patch ---
From: klp-build-test <test@example.com>
Subject: [PATCH] proc/cmdline: add debug message

Single-function livepatch test (cmdline-string).

Signed-off-by: klp-build-test <test@example.com>
---
 fs/proc/cmdline.c | 1 +
 1 file changed, 1 insertion(+)

diff --git a/fs/proc/cmdline.c b/fs/proc/cmdline.c
index 91fe1597af7d..84c1f2466611 100644
--- a/fs/proc/cmdline.c
+++ b/fs/proc/cmdline.c
@@ -8,6 +8,7 @@

 static int cmdline_proc_show(struct seq_file *m, void *v)
 {
+	pr_info("klp-build-test: cmdline_proc_show called\n");
 	seq_puts(m, saved_command_line);
 	seq_putc(m, '\n');
 	return 0;
```

### Test models

The framework supports two test models:

1. **Current-tree tests** (`tests/current-tree/`) — Static `.patch` files applied against the unmodified kernel source tree. These test klp-build's handling of real kernel code: multi-file patches, patches that add/remove files, various failure modes, etc.

2. **Patched-tree tests** (`tests/patched-tree/`) — Tests that first modify the kernel source tree with custom test code, then run klp-build against livepatch patches targeting that code. A self-contained base patch (`tests/patched-tree/base/kernel-test-infra.patch`) adds simple test functions with `/proc` interfaces to `kernel/livepatch/`. This base patch is applied at test time and reverted afterward. Individual tests provide livepatch source patches that modify the base test code. This model enables testing of specific scenarios (vmlinux vs module patching, ThinLTO symbol correlation, visibility changes) without depending on any particular kernel function.

---

## 3. Livepatch runtime verification

Runtime tests load the built `.ko` into a running kernel and verify behavior (e.g. enable/disable livepatch, check semantics). They run in the context of whatever profile produced the artifacts—and, as with build tests, outcomes can differ by profile. Root and a matching kernel are required.

### Require certain config/profile

- Runtime tests need a **built `.ko`**. The runner looks under `artifacts/*/<tree>/<test_basename>/*.ko` (search is across all profile directories). If a `.ko` exists for that test in any profile's artifact dir, the test can run; there is no separate "profile required" list.

### Verification checks

- Each test's `expected.verify_runtime(runtime)` is called. A list of verification steps can be recorded and written to the runtime log. In addition, dmesg is checked for overflow and for kernel call traces; any such issues are reported and can fail the test.

### Example runtime-test.log

The runtime log is written to `artifacts/<profile>/<tree>/<test_name>/runtime-test.log`. Example:

```
======================================================================
RUNTIME LOG: current-tree/pass/quick/cmdline-string
======================================================================
Verdict:    pass
Kernel:     6.19.0

======================================================================
RUNTIME VERIFICATION
======================================================================

# Read /proc/cmdline
$ cat /proc/cmdline
virtme_hostname=virtme-ng ... virtme.dhcp net.ifnames=0 ...

======================================================================
DMESG LOG (captured during test)
======================================================================
[Tue Mar  3 13:20:39 2026] livepatch_cmdline_string: loading out-of-tree module taints kernel.
[Tue Mar  3 13:20:39 2026] livepatch_cmdline_string: tainting kernel with TAINT_LIVEPATCH
[Tue Mar  3 13:20:39 2026] livepatch: enabling patch 'livepatch_cmdline_string'
[Tue Mar  3 13:20:39 2026] livepatch: 'livepatch_cmdline_string': starting patching transition
[Tue Mar  3 13:20:40 2026] livepatch: 'livepatch_cmdline_string': patching complete
[Tue Mar  3 13:20:40 2026] klp-build-test: cmdline_proc_show called
```

---

## 4. Directory structure (with artifacts/)

Below is a tree-style view of the selftest directory. Tests are split into `current-tree/` (patches against the unmodified kernel) and `patched-tree/` (patches against modified test code). Build and runtime outputs are grouped by profile under `artifacts/<profile>/`; within each profile dir, artifacts are organized by tree type (e.g. test `current-tree/pass/quick/cmdline-string` → `artifacts/<profile>/current-tree/cmdline-string`).

```
tools/testing/selftests/klp-build
├── Makefile
├── apply_profile.py
├── run_build_tests.py
├── run_runtime_tests.py
├── lib
│   ├── __init__.py
│   ├── build_log.py
│   ├── elf_inspect.py
│   ├── klp_build.py
│   ├── livepatch.py
│   ├── patched_tree.py
│   ├── profile.py
│   ├── requirements.py
│   ├── state.py
│   ├── test_discovery.py
│   └── verification.py
├── profiles
│   ├── 0000-klp-build.fragment
│   ├── full-default
│   │   └── config.yaml
│   ├── full-fedora-43
│   │   └── config.yaml
│   ├── full-openSUSE-leap
│   │   └── config.yaml
│   ├── full-openSUSE-tumbleweed
│   │   └── config.yaml
│   ├── full-rhel-10.2
│   │   └── config.yaml
│   ├── full-rhel-10.2-debug
│   │   └── config.yaml
│   ├── full-rhel-10.2-rt
│   │   └── config.yaml
│   ├── full-ubuntu-25
│   │   └── config.yaml
│   ├── full-virtme-ng
│   │   └── config.yaml
│   ├── overlay-klp-build
│   │   └── config.yaml
│   ├── overlay-llvm
│   │   └── config.yaml
│   ├── overlay-thin-lto
│   │   ├── config.yaml
│   │   └── 0001-thin-lto.fragment
│   └── overlay-virtme-ng
│       └── config.yaml
├── tests
│   ├── current-tree
│   │   ├── pass
│   │   │   ├── quick
│   │   │   │   └── cmdline-string
│   │   │   │       ├── expected.py
│   │   │   │       └── cmdline-string.patch
│   │   │   └── long
│   │   │       ├── add-remove-file-diff
│   │   │       │   ├── expected.py
│   │   │       │   └── ...
│   │   │       └── ...
│   │   └── fail
│   │       ├── quick
│   │       │   └── ...
│   │       └── long
│   │           └── ...
│   └── patched-tree
│       ├── base
│       │   ├── expected.py
│       │   └── kernel-test-infra.patch
│       └── pass
│           ├── vmlinux
│           │   ├── expected.py
│           │   └── vmlinux.patch
│           ├── module
│           │   ├── expected.py
│           │   └── module.patch
│           └── ...
└── artifacts
    └── full-virtme-ng+overlay-thin-lto
        ├── config
        ├── profile
        ├── current-tree
        │   ├── cmdline-string
        │   │   ├── build-test.log
        │   │   ├── runtime-test.log
        │   │   └── <module>.ko
        │   ├── add-remove-file-diff
        │   │   ├── build-test.log
        │   │   ├── <module>.ko
        │   │   └── runtime-test.log
        │   └── ...
        └── patched-tree
            ├── vmlinux
            │   ├── build-test.log
            │   ├── runtime-test.log
            │   └── <module>.ko
            └── ...
```

---

## 5. Makefile targets

Run from kernel source root: `make -C tools/testing/selftests/klp-build <target>`.

| Target | Description |
|--------|-------------|
| `tests_config` | No PROFILE: if no `.config`, run defconfig then merge default klp-build fragment; if `.config` exists, merge fragment only. With `PROFILE=<name-or-chain>`: apply that profile or chain (e.g. `PROFILE=full-default+overlay-thin-lto`). |
| `build_tests TREE=current` | Run current-tree build tests. `TREE=` is required (`current` or `patched`). No PROFILE: use current `.config`. With `PROFILE=a b c`: stash `.config`, apply each profile in turn, run build tests for it, then restore `.config`. |
| `build_tests TREE=patched` | Run patched-tree build tests. Same PROFILE handling as above. |
| `build_tests_quick` | Run quick current-tree tests only (`current-tree/pass/quick`, `current-tree/fail/quick`). |
| `runtime_tests` | Run runtime verification tests. Auto-detects a virtme-ng profile in `artifacts/` and uses VM mode (`--vng`) when found. |
| `report` | Generate `artifacts/report.txt` and `artifacts/report.html` — a profile × test pass/fail/skip matrix from the build and runtime logs in `artifacts/`. |
| `clean` | Remove `__pycache__`, `*-generated.patch` under tests, and the `artifacts/` directory. |
| `help` | Print a short description of each target. |

---

## 6. Example session

Full workflow from a clean tree to runtime tests. All commands are run from the **kernel source root**.

```bash
# 0) Abbreviate the long path
KLP_DIR="tools/testing/selftests/klp-build"

# 1) Clean kernel tree and selftest (including artifacts and generated patches)
make clean && make mrproper && make -C "$KLP_DIR" clean

# 2) Apply a full profile to get a .config (e.g. for virtme-ng)
make -C "$KLP_DIR" tests_config PROFILE="virtme-ng"

# 3) Run build tests (current-tree patches)
make -C "$KLP_DIR" build_tests TREE=current

# 4) Run runtime tests (current-tree patches)
make -C "$KLP_DIR" runtime_tests

# 5) Run build tests (patched-tree patches)
make -C "$KLP_DIR" build_tests TREE=patched

# 6) Run runtime tests (patched-tree patches)
make -C "$KLP_DIR" runtime_tests

# 7) Create a report
make -C "$KLP_DIR" report
```

If you create a .config with the "virtme-ng" profile, the `runtime_tests` target will detect this and run the livepatch load / verification tests in a virtme-ng session. (You can also run `./run_runtime_tests.py --vng` from `tools/testing/selftests/klp-build`.)

Sample reports: [HTML](https://file.rdu.redhat.com/~jolawren/artifacts/report.html), [text](https://file.rdu.redhat.com/~jolawren/artifacts/report.txt).
