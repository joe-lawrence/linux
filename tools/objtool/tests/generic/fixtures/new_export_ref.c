// SPDX-License-Identifier: GPL-2.0
/*
 * A reference which only exists in the patched build.  The symbol has no twin
 * in the original object, so what klp diff may do with it depends entirely on
 * whether Module.symvers says it is exported, and by what.
 */

static const char __modinfo[]
	__attribute__((section(".modinfo"), used, aligned(1))) = "\0name=vmlinux";

extern int newly_referenced(int x);

int target(int x)
{
#ifdef PATCHED
	return newly_referenced(x);
#else
	return x + 1;
#endif
}
