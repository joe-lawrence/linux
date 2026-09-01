#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
#
# Correlating ThinLTO-promoted locals requires demangling the .llvm.<hash>
# suffix, and the resulting klp relocation must name the original symbol: that
# is the one in the running kernel's kallsyms.

. "$(dirname "$0")/../lib.sh"

setup

# A ThinLTO link needs a clang and an lld from the same LLVM release; a
# mismatched pair fails with "Invalid summary version", which reads like a
# broken test rather than a broken environment.  So look for a pair which
# actually works together rather than assuming the first of each on $PATH.
#
# $CC may not be clang at all, and this is still worth running when a clang is
# installed beside a gcc $CC -- which is why the search is here and not in
# preflight, whose business is the capabilities of $CC itself.  Set THIN_CC and
# THIN_LD to skip the search.
find_thinlto_toolchain()
{
	local cc ld ver

	for cc in "${THIN_CC:-}" "$CC" clang; do
		[ -n "$cc" ] || continue
		command -v "${cc%% *}" >/dev/null 2>&1 || continue

		$cc -flto=thin -O2 -c "$FIXTURES_DIR/thinlto_local.c" \
			-o "$workdir/probe.o" 2>/dev/null || continue

		ver=$($cc -dumpversion 2>/dev/null | cut -d. -f1)

		for ld in "${THIN_LD:-}" "ld.lld-$ver" ld.lld; do
			[ -n "$ld" ] || continue
			command -v "$ld" >/dev/null 2>&1 || continue
			"$ld" -r "$workdir/probe.o" -o "$workdir/probe.elf" \
				2>/dev/null || continue

			THIN_CC="$cc"
			THIN_LD="$ld"
			return 0
		done
	done

	return 1
}

find_thinlto_toolchain ||
	probe_skip "no matching clang/lld pair for a ThinLTO link; set THIN_CC and THIN_LD to one"

build_thinlto()		# $1 output object, $2 extra flags
{
	$THIN_CC -flto=thin -O2 -ffunction-sections -fdata-sections $2 \
		-c "$FIXTURES_DIR/thinlto_local.c" -o "$workdir/tu_a.o" 2>/dev/null || return 1
	$THIN_CC -flto=thin -O2 -ffunction-sections -fdata-sections $2 -DTU_B \
		-c "$FIXTURES_DIR/thinlto_local.c" -o "$workdir/tu_b.o" 2>/dev/null || return 1
	"$THIN_LD" -r "$workdir/tu_a.o" "$workdir/tu_b.o" -o "$1" 2>/dev/null || return 1
}

build_thinlto "$workdir/orig.o" ""           || probe_skip "ThinLTO build failed ($THIN_CC, $THIN_LD)"
build_thinlto "$workdir/patched.o" -DPATCHED || probe_skip "ThinLTO build failed ($THIN_CC, $THIN_LD)"

orig_sym="$(in_symbols orig.o    | grep -o 'counter\.llvm\.[0-9]*' | head -1)"
new_sym="$( in_symbols patched.o | grep -o 'counter\.llvm\.[0-9]*' | head -1)"

[ -n "$orig_sym" ] && [ -n "$new_sym" ] ||
	probe_skip "$THIN_CC did not promote the local symbol"

# Equal hashes would make plain name matching work, testing nothing.
[ "$orig_sym" != "$new_sym" ] ||
	probe_skip "$THIN_CC gave the same ThinLTO hash for both builds"

run_diff
assert_patched target

out_symbols | grep -q "\.klp\.sym\.vmlinux\.$orig_sym," ||
	fail "expected a klp relocation naming $orig_sym"
out_symbols | grep -q "\.klp\.sym\.vmlinux\.$new_sym," &&
	fail "klp relocation names $new_sym, which the running kernel does not have"

# Name the toolchain: it is not $CC, and under a gcc run nothing else in the
# output says a clang was involved at all.
pass "ThinLTO-mangled local correlated across differing hashes ($THIN_CC, $THIN_LD)"
