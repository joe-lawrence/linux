#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
#
# A function's checksum must not depend on where the function sits.
#
# A jump or call without a relocation encodes its target as an offset from the
# instruction.  Hashing those bytes makes the checksum change whenever anything
# ahead of the function changes size -- so an unrelated edit elsewhere in the
# file reports this function as changed too, and the patch grows to include it
# and everything it references.  Nothing fails; the livepatch is just larger and
# riskier than the patch it came from.
#
# Here the "patch" adds a function ahead of target() and changes nothing else.

. "$(dirname "$0")/../lib.sh"

setup

# -fno-function-sections, or each function is at offset 0 of its own section
# and target() never moves.
build_pair checksum_position.c -fno-function-sections

assert_input_symbol target

# The fixture is only meaningful if target() actually moved.
orig_off="$(in_symbols orig.o    | awk '$8 == "target" { print $2 }')"
new_off="$( in_symbols patched.o | awk '$8 == "target" { print $2 }')"
[ -n "$orig_off" ] && [ -n "$new_off" ] ||
	fail "target symbol not found in both objects"
[ "$orig_off" != "$new_off" ] ||
	probe_skip "compiler did not move target() between builds"

assert_checksum_matches target

pass "checksum unchanged when the function only moves"
