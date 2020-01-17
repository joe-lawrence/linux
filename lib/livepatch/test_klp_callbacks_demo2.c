// SPDX-License-Identifier: GPL-2.0
// Copyright (C) 2018 Joe Lawrence <joe.lawrence@redhat.com>

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/livepatch.h>
#include "test_klp_callbacks_demo2.h"

static int replace;
module_param(replace, int, 0644);
MODULE_PARM_DESC(replace, "replace (default=0)");

static const char *const module_state[] = {
	[MODULE_STATE_LIVE]	= "[MODULE_STATE_LIVE] Normal state",
	[MODULE_STATE_COMING]	= "[MODULE_STATE_COMING] Full formed, running module_init",
	[MODULE_STATE_GOING]	= "[MODULE_STATE_GOING] Going away",
	[MODULE_STATE_UNFORMED]	= "[MODULE_STATE_UNFORMED] Still setting it up",
};

static void callback_info(const char *callback, struct klp_object *obj)
{
	struct module *mod;

	if (!obj->name) {
		pr_info("%s: vmlinux\n", callback);
		return;
	}

	mutex_lock(&module_mutex);
	mod = find_module(obj->name);
	if (mod) {
		pr_info("%s: %s -> %s\n", callback, obj->name,
			module_state[mod->state]);
	} else {
		pr_err("%s: Unable to find module: %s", callback, obj->name);
	}
	mutex_unlock(&module_mutex);
}

/* Executed on object patching (ie, patch enablement) */
int pre_patch_callback2(struct klp_object *obj)
{
	callback_info(__func__, obj);
	return 0;
}
EXPORT_SYMBOL(pre_patch_callback2);

/* Executed on object unpatching (ie, patch disablement) */
void post_patch_callback2(struct klp_object *obj)
{
	callback_info(__func__, obj);
}
EXPORT_SYMBOL(post_patch_callback2);

/* Executed on object unpatching (ie, patch disablement) */
void pre_unpatch_callback2(struct klp_object *obj)
{
	callback_info(__func__, obj);
}
EXPORT_SYMBOL(pre_unpatch_callback2);

/* Executed on object unpatching (ie, patch disablement) */
void post_unpatch_callback2(struct klp_object *obj)
{
	callback_info(__func__, obj);
}
EXPORT_SYMBOL(post_unpatch_callback2);

static struct klp_func no_funcs[] = {
	{ }
};

static struct klp_object obj = {
	.patch_name = LIVEPATCH_NAME,
	.name = NULL,	/* vmlinux */
	.mod = THIS_MODULE,
	.funcs = no_funcs,
	.callbacks = {
		.pre_patch = pre_patch_callback2,
		.post_patch = post_patch_callback2,
		.pre_unpatch = pre_unpatch_callback2,
		.post_unpatch = post_unpatch_callback2,
	},
};

static char *obj_names[] = {
	NULL
};

static struct klp_patch patch = {
	.obj = &obj,
	.obj_names = obj_names,
	/* set .replace in the init function below for demo purposes */
};

static int test_klp_callbacks_demo2_init(void)
{
	patch.replace = replace;
	return klp_enable_patch(&patch);
}

static void test_klp_callbacks_demo2_exit(void)
{
}

module_init(test_klp_callbacks_demo2_init);
module_exit(test_klp_callbacks_demo2_exit);
MODULE_LICENSE("GPL");
MODULE_INFO(livepatch, "Y");
MODULE_AUTHOR("Joe Lawrence <joe.lawrence@redhat.com>");
MODULE_DESCRIPTION("Livepatch test: livepatch demo2");
