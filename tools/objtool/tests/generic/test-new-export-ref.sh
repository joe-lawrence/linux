#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
#
# A reference the patch adds has no counterpart in the original object.  klp
# diff used to reject any such reference needing a klp relocation, which ruled
# out patches that call something they did not call before -- a common enough
# thing for a fix to do.
#
# Module.symvers is what makes it safe: it says the symbol exists and who owns
# it.  But that is only sufficient for a vmlinux export.  A new reference to a
# module's export is a dependency the patch module does not declare, and the
# relocation would resolve only if that module happened to be loaded, so it
# stays an error.

. "$(dirname "$0")/../lib.sh"

setup
build_pair new_export_ref.c

# Exported by vmlinux, in a module: namespace so it needs a klp relocation
# rather than an ordinary one.  Allowed.
export_syms
add_exports_ns vmlinux module:kvm newly_referenced
run_diff
assert_klp_sym newly_referenced vmlinux

# Exported by a module the patched object does not depend on.  Rejected, and
# for that reason rather than some other.
export_syms
add_exports other_mod newly_referenced
run_diff 255
assert_diff_log 'undeclared module dependency'

pass "new reference allowed to a vmlinux export, rejected for a module export"
