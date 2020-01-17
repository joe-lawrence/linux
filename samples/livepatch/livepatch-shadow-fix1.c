// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * Copyright (C) 2017 Joe Lawrence <joe.lawrence@redhat.com>
 */

/*
 * livepatch-shadow-fix1.c - Shadow variables, livepatch demo
 *
 * Purpose
 * -------
 *
 * Fixes the memory leak introduced in livepatch-shadow-mod through the
 * use of a shadow variable.  This fix demonstrates the "extending" of
 * short-lived data structures by patching its allocation and release
 * functions.
 *
 *
 * Usage
 * -----
 *
 * This module is not intended to be standalone.  See the "Usage"
 * section of livepatch-shadow-mod.c.
 */

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/livepatch.h>

static struct klp_func no_funcs[] = {
	{}
};

static struct klp_object obj = {
	.patch_name = THIS_MODULE->name,
	.name = NULL,	/* vmlinux */
	.mod = THIS_MODULE,
	.funcs = no_funcs,
};

static char *obj_names[] = {
	"livepatch_shadow_mod",
	NULL
};

static struct klp_patch patch = {
	.obj = &obj,
	.obj_names = obj_names,
};

static int livepatch_shadow_fix1_init(void)
{
	return klp_enable_patch(&patch);
}

static void livepatch_shadow_fix1_exit(void)
{
}

module_init(livepatch_shadow_fix1_init);
module_exit(livepatch_shadow_fix1_exit);
MODULE_LICENSE("GPL");
MODULE_INFO(livepatch, "Y");
