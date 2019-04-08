// SPDX-License-Identifier: GPL-2.0
// Copyright (C) 2019 Joe Lawrence <joe.lawrence@redhat.com>

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/livepatch.h>
#include <linux/jump_label.h>
#include "trace.h"

/* klp_key - module local symbol */
static struct static_key_false klp_key;
static bool klp_key_enable;

static int set_klp_key_enable(const char *val,
				     const struct kernel_param *kp)
{
	int ret;

	trace_test_klp_static_keys(__func__);

	ret = param_set_bool(val, kp);
	if (ret)
		return ret;

	if (klp_key_enable) {
		static_branch_enable(&klp_key);
		pr_info("static_branch_enable(&klp_key)\n");
	} else {
		static_branch_disable(&klp_key);
		pr_info("static_branch_disable(&klp_key)\n");
	}

	return 0;
}

static int get_klp_key_enable(char *val, const struct kernel_param *kp)
{
	trace_test_klp_static_keys(__func__);

	pr_info("%s: klp_key_enable is %s\n", __func__,
		klp_key_enable ? "true" : "false");
	pr_info("%s: static_branch_unlikely is %s\n", __func__,
		static_branch_unlikely(&klp_key) ? "true" : "false");

	return param_get_bool(val, kp);
}

module_param_call(klp_key_enable, set_klp_key_enable,
		  get_klp_key_enable, &klp_key_enable, 0644);
MODULE_PARM_DESC(klp_key_enable, "Static branch enable");


/* klp-convert symbols - test_klp_static_keys_mod.ko */
extern struct static_key_false module_key;
extern bool module_key_enable;

static int klp_set_module_key_enable(const char *val,
				     const struct kernel_param *kp)
{
	int ret;

	trace_test_klp_static_keys(__func__);

	ret = param_set_bool(val, kp);
	if (ret)
		return ret;

	if (module_key_enable) {
		static_branch_enable(&module_key);
		pr_info("static_branch_enable(&module_key)\n");
	} else {
		static_branch_disable(&module_key);
		pr_info("static_branch_disable(&module_key)\n");
	}

	return 0;
}

static int klp_get_module_key_enable(char *val, const struct kernel_param *kp)
{
	trace_test_klp_static_keys(__func__);

	pr_info("%s: module_key_enable is %s\n", __func__,
		module_key_enable ? "true" : "false");
	pr_info("%s: static_branch_unlikely is %s\n", __func__,
		static_branch_unlikely(&module_key) ? "true" : "false");

	return param_get_bool(val, kp);
}

/* klp-convert symbols - test_klp_static_keys_mod.ko */
extern struct static_key_false module_key2;
extern bool module_key2_enable;

static int klp_set_module_key2_enable(const char *val,
				      const struct kernel_param *kp)
{
	int ret;

	trace_test_klp_static_keys(__func__);

	ret = param_set_bool(val, kp);
	if (ret)
		return ret;

	if (module_key2_enable) {
		static_branch_enable(&module_key2);
		pr_info("static_branch_enable(&module_key2)\n");
	} else {
		static_branch_disable(&module_key2);
		pr_info("static_branch_disable(&module_key2)\n");
	}

	return 0;
}

static int klp_get_module_key2_enable(char *val, const struct kernel_param *kp)
{
	trace_test_klp_static_keys(__func__);

	pr_info("%s: module_key2_enable is %s\n", __func__,
		module_key2_enable ? "true" : "false");
	pr_info("%s: static_branch_likely is %s\n", __func__,
		static_branch_likely(&module_key2) ? "true" : "false");

	return param_get_bool(val, kp);
}

static struct klp_func funcs[] = {
	{
		.old_name = "set_module_key_enable",
		.new_func = klp_set_module_key_enable,
	},
	{
		.old_name = "get_module_key_enable",
		.new_func = klp_get_module_key_enable,
	},
	{
		.old_name = "set_module_key2_enable",
		.new_func = klp_set_module_key2_enable,
	},
	{
		.old_name = "get_module_key2_enable",
		.new_func = klp_get_module_key2_enable,
	}, { }
};

static struct klp_object objs[] = {
	{
		.name = "test_klp_static_keys_mod",
		.funcs = funcs,
	}, { }
};

static struct klp_patch patch = {
	.mod = THIS_MODULE,
	.objs = objs,
};

static int test_klp_static_keys_init(void)
{
	trace_test_klp_static_keys(__func__);

	return klp_enable_patch(&patch);
}

static void test_klp_static_keys_exit(void)
{
}

module_init(test_klp_static_keys_init);
module_exit(test_klp_static_keys_exit);
MODULE_LICENSE("GPL");
MODULE_INFO(livepatch, "Y");
MODULE_AUTHOR("Joe Lawrence <joe.lawrence@redhat.com>");
MODULE_DESCRIPTION("Livepatch test: static keys");
