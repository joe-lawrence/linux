// SPDX-License-Identifier: GPL-2.0
// Copyright (C) 2020 Joe Lawrence <joe.lawrence@redhat.com>

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/livepatch.h>
#include <linux/jump_label.h>

/* klp-convert symbols - test_klp_keys_mod.ko */
extern struct static_key_true test_klp_true_key;
extern struct static_key_false test_klp_false_key;

/*
 * Carry our own copy of print_key_status() as we want static key code
 * patching updates to occur in the livepatch module as well as the
 * target module that defines the static keys.
 */
static void print_key_status(char *msg)
{
	pr_info("%s: %s\n", __func__, msg);

	/* static_key_enable() only tests the key value */
	pr_info("static_key_enabled(&test_klp_true_key) is %s\n",
		static_key_enabled(&test_klp_true_key) ? "true" : "false");
	pr_info("static_key_enabled(&test_klp_false_key) is %s\n",
		static_key_enabled(&test_klp_false_key) ? "true" : "false");

	/*
	 * static_branch_(un)likely() requires code patching when the
	 * key value changes
	 */
	pr_info("static_branch_likely(&test_klp_true_key) is %s\n",
		static_branch_likely(&test_klp_true_key) ? "true" : "false");
	pr_info("static_branch_unlikely(&test_klp_false_key) is %s\n",
		static_branch_unlikely(&test_klp_false_key) ? "true" : "false");
}

/*
 * sysfs interface to poke the key
 */
static bool enable_false_key;
static int set_enable_false_key(const char *val, const struct kernel_param *kp)
{
	print_key_status("set_enable_false_key start");
	static_branch_enable(&test_klp_false_key);
	print_key_status("set_enable_false_key enabling test_klp_false_key");

	return 0;
}
module_param_call(enable_false_key, set_enable_false_key, NULL, &enable_false_key, 0644);
MODULE_PARM_DESC(enable_false_key, "Static branch enable");


static struct klp_func funcs[] = {
	{ }
};

static struct klp_object obj = {
	.patch_name = "test_klp_keys",
	.name = "test_klp_keys_mod",
	.mod = THIS_MODULE,
	.funcs = funcs,
};

static int test_klp_keys__test_klp_keys_mod_init(void)
{
	return klp_add_object(&obj);
}

static void test_klp_keys__test_klp_keys_mod_exit(void)
{
}

module_init(test_klp_keys__test_klp_keys_mod_init);
module_exit(test_klp_keys__test_klp_keys_mod_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Joe Lawrence <joe.lawrence@redhat.com>");
MODULE_DESCRIPTION("Livepatch test: static keys");
MODULE_INFO(livepatch, "Y");
