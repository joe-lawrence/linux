// SPDX-License-Identifier: GPL-2.0
// Copyright (C) 2018 Joe Lawrence <joe.lawrence@redhat.com>

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/livepatch.h>
#include "test_klp_callbacks_demo.h"

static struct klp_func no_funcs[] = {
	{}
};

static struct klp_object obj = {
	.patch_name = LIVEPATCH_NAME,
	.name = "test_klp_module",
	.mod = THIS_MODULE,
	.funcs = no_funcs,
	.callbacks = {
		.pre_patch = pre_patch_callback,
		.post_patch = post_patch_callback,
		.pre_unpatch = pre_unpatch_callback,
		.post_unpatch = post_unpatch_callback,
	},
};

static int test_klp_callbacks_demo_init(void)
{
	return klp_add_object(&obj);
}

static void test_klp_callbacks_demo_exit(void)
{
}

module_init(test_klp_callbacks_demo_init);
module_exit(test_klp_callbacks_demo_exit);
MODULE_LICENSE("GPL");
MODULE_INFO(livepatch, "Y");
MODULE_AUTHOR("Joe Lawrence <joe.lawrence@redhat.com>");
MODULE_DESCRIPTION("Livepatch test: livepatch demo");
