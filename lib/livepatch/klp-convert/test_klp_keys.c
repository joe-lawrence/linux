// SPDX-License-Identifier: GPL-2.0
// Copyright (C) 2020 Joe Lawrence <joe.lawrence@redhat.com>

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/livepatch.h>

static struct klp_func funcs[] = {
	{
	}, { }
};

static struct klp_object obj = {
	.patch_name = "test_klp_keys",
	.name = NULL,   /* vmlinux */
	.mod = THIS_MODULE,
	.funcs = funcs,
};

static char *obj_names[] = {
	"test_klp_keys_mod",
	NULL
};

static struct klp_patch patch = {
	.obj = &obj,
	.obj_names = obj_names,
};

static int test_klp_convert_keys_init(void)
{
	int ret;

	ret = klp_enable_patch(&patch);
	if (ret)
		return ret;

	return 0;
}

static void test_klp_convert_keys_exit(void)
{
}

module_init(test_klp_convert_keys_init);
module_exit(test_klp_convert_keys_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Joe Lawrence <joe.lawrence@redhat.com>");
MODULE_DESCRIPTION("Livepatch test: static keys");
MODULE_INFO(livepatch, "Y");
