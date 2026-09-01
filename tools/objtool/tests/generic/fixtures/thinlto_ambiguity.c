// SPDX-License-Identifier: GPL-2.0
/*
 * Three translation units linked with ThinLTO, two of which have a file-local
 * helper of the same name.
 *
 * TU_C calls into both of the others, so ThinLTO imports entry_a and entry_b
 * and with them the static helper each one calls.  A file-local symbol which
 * has to become visible is renamed helper.llvm.<hash>, and the hash is content
 * derived -- so the two helpers get different hashes from each other, and
 * different ones again after the patch changes them both.
 *
 * That leaves klp diff with two symbols in the original and two in the patched
 * object, all four named differently, which have to be paired up correctly.
 * Demangling alone gives "helper" for all of them; something else has to
 * decide which is which.
 *
 * Only TU_A's helper changes.  That is what makes a wrong pairing observable:
 * paired correctly, one helper is changed and the other is not, so exactly one
 * is cloned.  Paired the wrong way round, both look changed -- or the wrong
 * one does.  If both bodies changed the outcome would be the same either way
 * and the test would prove nothing.
 *
 * BASE differs between the two so their bodies are not identical to begin
 * with.
 */

#if defined(TU_C)
extern int entry_a(int);
extern int entry_b(int);
int glue(int x) { return entry_a(x) + entry_b(x + 1); }
#else
#ifdef TU_B
#define ENTRY entry_b
#define BASE 5
#else
#define ENTRY entry_a
#define BASE 10
static const char __modinfo[] __attribute__((section(".modinfo"), used, aligned(1))) = "\0name=vmlinux";
#endif
static __attribute__((noinline)) int helper(int x, int len)
{
	int sum = 0, i;
	for (i = 0; i < len; i++)
#if defined(PATCHED) && !defined(TU_B)
		sum += i * 2 + BASE;	/* only TU_A's helper changes */
#else
		sum += i + BASE;
#endif
	return sum + x;
}
int ENTRY(int x) { return helper(x, 4); }
#endif
