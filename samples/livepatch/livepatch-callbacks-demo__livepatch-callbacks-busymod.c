// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * Copyright (C) 2017 Joe Lawrence <joe.lawrence@redhat.com>
 */

/*
 * livepatch-callbacks-demo.c - (un)patching callbacks livepatch demo
 */

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/livepatch.h>
#include "livepatch-callbacks-demo.h"

static void patched_work_func(struct work_struct *work)
{
	pr_info("%s\n", __func__);
}

static struct klp_func busymod_funcs[] = {
	{
		.old_name = "busymod_work_func",
		.new_func = patched_work_func,
	}, { }
};

static struct klp_object obj = {
	.patch_name = LIVEPATCH_NAME,
	.name = "livepatch_callbacks_busymod",
	.mod = THIS_MODULE,
	.funcs = busymod_funcs,
	.callbacks = {
		.pre_patch = sample_pre_patch_callback,
		.post_patch = sample_post_patch_callback,
		.pre_unpatch = sample_pre_unpatch_callback,
		.post_unpatch = sample_post_unpatch_callback,
	},
};

static int livepatch_callbacks_demo_init(void)
{
	return klp_add_object(&obj);
}

static void livepatch_callbacks_demo_exit(void)
{
}

module_init(livepatch_callbacks_demo_init);
module_exit(livepatch_callbacks_demo_exit);
MODULE_LICENSE("GPL");
MODULE_INFO(livepatch, "Y");
