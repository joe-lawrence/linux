// SPDX-License-Identifier: GPL-2.0
// Copyright (C) 2019 Joe Lawrence <joe.lawrence@redhat.com>

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/livepatch.h>


static struct klp_object objs[] = {
	{ }
};

static struct klp_blacklist srcvers[] = {
	{
	}, { }
};

static struct klp_patch patch = {
	.mod = THIS_MODULE,
	.objs = objs,
	.blacklist = srcvers,
};

static char *srcversion;
module_param(srcversion, charp, 0444);
MODULE_PARM_DESC(srcversion, "srcversion");

static int test_klp_blacklist_init(void)
{
	patch.blacklist[0].srcversion = srcversion;
	return klp_enable_patch(&patch);
}

static void test_klp_blacklist_exit(void)
{
}

module_init(test_klp_blacklist_init);
module_exit(test_klp_blacklist_exit);
MODULE_LICENSE("GPL");
MODULE_INFO(livepatch, "Y");
MODULE_AUTHOR("Joe Lawrence <joe.lawrence@redhat.com>");
MODULE_DESCRIPTION("Livepatch test: livepatch blacklist module");
