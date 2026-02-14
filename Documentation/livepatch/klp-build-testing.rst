.. SPDX-License-Identifier: GPL-2.0

=====================================
klp-build selftests: config profiles
=====================================

Overview
--------

The klp-build selftests (under ``tools/testing/selftests/klp-build/``) use
config profiles to set up a kernel ``.config`` and optional toolchain for
testing. Profiles are either **full** (they produce an entire .config) or
**overlay** (they merge fragments on top of an existing .config).

Config profiles
---------------

Profiles live under ``profiles/<name>/`` with a ``config.yaml`` file. The
profile type is inferred from the directory name: ``full-*`` is a full
profile, ``overlay-*`` is an overlay.

**Full profiles** have ``config_base`` (e.g. ``make defconfig`` or
``virtme-ng --kconfig``) and optionally ``config_apply`` (fragments merged
after the base). They overwrite or create ``.config``.

**Overlay profiles** have only ``config_apply`` (no ``config_base``). They
merge their fragments into the current ``.config`` (or the result of a
previous profile in a chain). Overlays can optionally set a **toolchain**
(compiler, linker, assembler) in the YAML.

Verification runs after applying a profile or chain: only the options from
**config_apply** fragments are checked in the final ``.config``; ``config_base``
is not verified (so a user-provided base or local defaults can change options).

PROFILE chain
-------------

You can apply a single profile or a **chain** (e.g. full then overlay) by
setting ``PROFILE=full-default+overlay-thin-lto``. Profiles are applied in
order; the **effective toolchain** is taken from the last profile in the
chain that defines one. That toolchain (and ``LLVM=1`` when the compiler is
clang) is set before any config step so that the base config is built with
the same toolchain the overlay expects.

- **Conflicting toolchains**: If two profiles in the chain specify different
  toolchain values, the apply errors out.
- **Overlay on existing .config**: If you apply an overlay that sets a
  toolchain on top of an existing ``.config`` (e.g. one built with gcc), a
  warning is printed; the apply still runs.
- **Implied toolchain**: If the effective toolchain comes from a profile
  that is not the first in the chain (e.g. from ``overlay-thin-lto`` in
  ``full-default+overlay-thin-lto``), a note is printed that this profile
  sets the toolchain for the whole chain.

Chains must contain at most one full profile (e.g. ``full-default+full-virtme-ng``
is invalid).

Make target: tests_config
-------------------------

From the kernel source root::

  make -C tools/testing/selftests/klp-build tests_config [PROFILE=<name-or-chain>]

- **No PROFILE**: If no ``.config`` exists, runs ``make defconfig`` then
  merges the default klp-build fragment and ``make olddefconfig``. If
  ``.config`` exists, merges only the default klp-build fragment and
  ``make olddefconfig``.
- **PROFILE=overlay-only, no .config**: Skips (exit 77, kselftest skip).
- **PROFILE=full-default** (or other full profile): Applies that profile;
  overwrites or creates ``.config``.
- **PROFILE=full-default+overlay-thin-lto** (chain): Applies the full profile
  then the overlay(s); toolchain from the overlay is used for the whole chain.

Out-of-the-box profiles
-----------------------

- **full-default**: ``make defconfig`` + klp-build fragment (livepatch +
  klp-build options).
- **full-virtme-ng**: ``virtme-ng --kconfig`` + klp-build fragment.
- **overlay-klp-build**: Klp-build fragment only; use when you already have
  a ``.config``.
- **overlay-thin-lto**: Klp-build fragment + thin LTO fragment; sets
  toolchain to clang/ld.lld and ``LLVM=1`` for defconfig/olddefconfig.

Example commands
----------------

::

  # No .config: create one with defconfig + klp-build fragment
  make -C tools/testing/selftests/klp-build tests_config

  # .config exists: merge only the klp-build fragment
  make -C tools/testing/selftests/klp-build tests_config

  # Full profile
  make -C tools/testing/selftests/klp-build tests_config PROFILE=full-default

  # Chain: full base then overlay (e.g. thin LTO); toolchain set from overlay
  make -C tools/testing/selftests/klp-build tests_config PROFILE=full-default+overlay-thin-lto

  # Overlay on current .config (may warn if overlay sets a toolchain)
  make -C tools/testing/selftests/klp-build tests_config PROFILE=overlay-thin-lto

Requirements
------------

- PyYAML for profile loading: ``pip install pyyaml``.
- For ``tests_config``: kernel source tree with ``scripts/kconfig/merge_config.sh``.
