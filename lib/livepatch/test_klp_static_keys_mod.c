// SPDX-License-Identifier: GPL-2.0
// Copyright (C) 2019 Joe Lawrence <joe.lawrence@redhat.com>

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/jump_label.h>

/*
 * Trace events are implemented on top of static keys, so
 * define and export a trace point for testing purposes.
 */
#define CREATE_TRACE_POINTS
#include "trace.h"
/*
 * XXX: Let klp-convert resolve test_klp_static_keys
 *
 * EXPORT_TRACEPOINT_SYMBOL_GPL(test_klp_static_keys);
 */

/*
 * module_key - default to false and export symbol
 */
static DEFINE_STATIC_KEY_FALSE(module_key);
EXPORT_SYMBOL(module_key);
static bool module_key_enable = false;

static int set_module_key_enable(const char *val,
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

static int get_module_key_enable(char *val, const struct kernel_param *kp)
{
	trace_test_klp_static_keys(__func__);

	pr_info("%s: module_key_enable is %s\n", __func__,
		module_key_enable ? "true" : "false");
	pr_info("%s: static_branch_unlikely is %s\n", __func__,
		static_branch_unlikely(&module_key) ? "true" : "false");

	return param_get_bool(val, kp);
}

module_param_call(module_key_enable, set_module_key_enable,
		  get_module_key_enable, &module_key_enable, 0644);
MODULE_PARM_DESC(module_key_enable, "Static branch enable");


/*
 * module_key2 - default to true
 */
static DEFINE_STATIC_KEY_TRUE(module_key2);
/*
 * XXX: Let klp-convert resolve module_key2
 *
 * EXPORT_SYMBOL(module_key2);
 */
static bool module_key2_enable = true;

static int set_module_key2_enable(const char *val,
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

static int get_module_key2_enable(char *val, const struct kernel_param *kp)
{
	trace_test_klp_static_keys(__func__);

	pr_info("%s: module_key2_enable is %s\n", __func__,
		module_key2_enable ? "true" : "false");
	pr_info("%s: static_branch_likely is %s\n", __func__,
		static_branch_likely(&module_key2) ? "true" : "false");

	return param_get_bool(val, kp);
}

module_param_call(module_key2_enable, set_module_key2_enable,
		  get_module_key2_enable, &module_key2_enable, 0644);
MODULE_PARM_DESC(module_key2_enable, "Static branch enable");


static int test_klp_static_keys_mod_init(void)
{
	trace_test_klp_static_keys(__func__);

	module_key_enable = static_branch_unlikely(&module_key);
	module_key2_enable = static_branch_likely(&module_key);
	return 0;
}

static void test_klp_static_keys_mod_exit(void)
{
	trace_test_klp_static_keys(__func__);
}

module_init(test_klp_static_keys_mod_init);
module_exit(test_klp_static_keys_mod_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Joe Lawrence <joe.lawrence@redhat.com>");
MODULE_DESCRIPTION("Livepatch test: busy target module");
