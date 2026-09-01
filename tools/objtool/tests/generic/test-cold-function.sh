#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
#
# Both halves of a split function belong to the patch; carrying only the hot
# part leaves the cold path branching into unpatched code.

. "$(dirname "$0")/../lib.sh"

# Clang does not split functions into a cold part at all, so there is nothing
# for this test to look at there.  A given gcc may or may not split, which is a
# version property rather than a compiler choice -- that stays a probe below.
gcc_only "clang does not split functions into a cold part"

setup

split_flag=-freorder-blocks-and-partition
cc_supports "$split_flag" || split_flag=

build_pair cold_function.c $split_flag

in_symbols orig.o | grep -qE 'target\.cold' ||
	probe_skip "compiler did not split the function into a cold part"

run_diff

assert_patched target
out_symbols | grep -qE 'target\.cold' ||
	fail "cold half was not carried into the patch"

pass "cold half carried into the patch with its parent"
