// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * Copyright (C) 2020 Matt Helsley <mhelsley@vmware.com>
 * Weak definitions necessary to compile objtool without
 * some subcommands (e.g. check, orc).
 */

#include <stdbool.h>
#include <errno.h>
#include <string.h>
#include <objtool/objtool.h>
#include <objtool/arch.h>
#include <objtool/check.h>
#include <objtool/builtin.h>

#define UNSUPPORTED(name)						\
({									\
	fprintf(stderr, "error: objtool: " name " not implemented\n");	\
	return ENOSYS;							\
})

int __weak orc_dump(const char *_objname)
{
	UNSUPPORTED("ORC");
}

int __weak orc_create(struct objtool_file *file)
{
	UNSUPPORTED("ORC");
}

int __weak cmd_klp(int argc, const char **argv)
{
	UNSUPPORTED("klp");
}

void __weak arch_jump_opcode_bytes(struct objtool_file *file,
				   struct instruction *insn,
				   unsigned char *buf, size_t *len)
{
	/*
	 * Nothing to see here.  This has no purpose other than to avoid
	 * breaking bisection builds.  It will be removed shortly.
	 */
}
