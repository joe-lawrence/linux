// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * livepatch-sample.c - Kernel Live Patching Sample Module
 *
 * Copyright (C) 2014 Seth Jennings <sjenning@redhat.com>
 */

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/livepatch.h>

/*
 * This (dumb) live patch overrides the function that prints the
 * kernel boot cmdline when /proc/cmdline is read.
 *
 * Example:
 *
 * $ cat /proc/cmdline
 * <your cmdline>
 *
 * $ insmod livepatch-sample.ko
 * $ cat /proc/cmdline
 * this has been live patched
 *
 * $ echo 0 > /sys/kernel/livepatch/livepatch_sample/enabled
 * $ cat /proc/cmdline
 * <your cmdline>
 */

#include <linux/seq_file.h>
static int livepatch_cmdline_proc_show(struct seq_file *m, void *v)
{
	seq_printf(m, "%s\n", "this has been live patched");
	return 0;
}

static struct klp_func funcs[] = {
	{
		.old_name = "cmdline_proc_show",
		.new_func = livepatch_cmdline_proc_show,
	}, { }
};

static char *obj_names[] = {
	NULL
};

static struct klp_object obj = {
	.patch_name = THIS_MODULE->name,
	.name = NULL,	/* vmlinux */
	.mod = THIS_MODULE,
	.funcs = funcs,
};

static struct klp_patch patch = {
	.obj = &obj,
	.obj_names = obj_names,
};

static int livepatch_init(void)
{
	return klp_enable_patch(&patch);
}

static void livepatch_exit(void)
{
}

module_init(livepatch_init);
module_exit(livepatch_exit);
MODULE_LICENSE("GPL");
MODULE_INFO(livepatch, "Y");
