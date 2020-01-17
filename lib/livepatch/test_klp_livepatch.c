// SPDX-License-Identifier: GPL-2.0
// Copyright (C) 2014 Seth Jennings <sjenning@redhat.com>

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/livepatch.h>

#include <linux/seq_file.h>
static int livepatch_cmdline_proc_show(struct seq_file *m, void *v)
{
	seq_printf(m, "%s: %s\n", THIS_MODULE->name,
		   "this has been live patched");
	return 0;
}

static struct klp_func funcs[] = {
	{
		.old_name = "cmdline_proc_show",
		.new_func = livepatch_cmdline_proc_show,
	}, { }
};

struct klp_object obj = {
	.patch_name = THIS_MODULE->name,
	.name = NULL,	/* vmlinux */
	.mod = THIS_MODULE,
	.funcs = funcs,
};

static char *obj_names[] = {
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
