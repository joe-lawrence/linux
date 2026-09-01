// SPDX-License-Identifier: GPL-2.0
/*
 * A function whose position in the section changes between the two builds,
 * without the function itself changing.
 *
 * PATCHED adds a function ahead of it, so target() moves.  It must be built
 * without -ffunction-sections, or every function sits at offset 0 of its own
 * section and nothing ever moves -- which is why the test passes
 * -fno-function-sections.
 *
 * target() contains a loop, so it has a relative jump with no relocation.  The
 * offset encoded in that instruction depends on where the function sits, and
 * hashing those bytes makes the checksum move when the function does.
 */

static const char __modinfo[]
	__attribute__((section(".modinfo"), used, aligned(1))) = "\0name=vmlinux";

__attribute__((noinline)) static int callee(int x)
{
	return x * 5 + 1;
}

/*
 * Inserted between callee() and target(), so the distance target's call has to
 * encode changes.  A jump or call within the same section needs no relocation:
 * the displacement is in the instruction, and it is that displacement which
 * moves.
 */
#ifdef PATCHED
__attribute__((noinline)) int padding(int x)
{
	int i, s = 0;

	for (i = 0; i < x; i++)
		s += i * 3;

	return s;
}
#endif

__attribute__((noinline)) int target(int x)
{
	return callee(x) + callee(x + 1);
}
