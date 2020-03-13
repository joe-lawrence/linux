// SPDX-License-Identifier: GPL-2.0
// Copyright (C) 2014 Seth Jennings <sjenning@redhat.com>

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/livepatch.h>

static struct klp_func no_funcs[] = {
	{}
};

static struct klp_object obj = {
	.patch_name = "test_klp_livepatch2",
	.name = NULL,	/* vmlinux */
	.mod = THIS_MODULE,
	.funcs = no_funcs,
};

static char *obj_names[] = {
	"test_klp_module",
	NULL
};

static struct klp_patch patch = {
	.obj = &obj,
	.obj_names = obj_names,
};

static int test_klp_livepatch_init(void)
{
	return klp_enable_patch(&patch);
}

static void test_klp_livepatch_exit(void)
{
}

module_init(test_klp_livepatch_init);
module_exit(test_klp_livepatch_exit);
MODULE_LICENSE("GPL");
MODULE_INFO(livepatch, "Y");
MODULE_AUTHOR("Seth Jennings <sjenning@redhat.com>");
MODULE_DESCRIPTION("Livepatch test: livepatch module");
