// SPDX-License-Identifier: GPL-2.0
// Copyright (C) 2018 Joe Lawrence <joe.lawrence@redhat.com>

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/kernel.h>

int get_klp_module_status(char *buffer, const struct kernel_param *kp)
{
        return scnprintf(buffer, PAGE_SIZE, "%s: status: unpatched\n",
			 THIS_MODULE->name);
}

static const struct kernel_param_ops test_ops = {
	.get = get_klp_module_status,
};
module_param_cb(status, &test_ops, NULL, 0444);

static int test_klp_module_init(void)
{
	pr_info("%s\n", __func__);
	return 0;
}

static void test_klp_module_exit(void)
{
	pr_info("%s\n", __func__);
}

module_init(test_klp_module_init);
module_exit(test_klp_module_exit);
MODULE_LICENSE("GPL");
MODULE_AUTHOR("Joe Lawrence <joe.lawrence@redhat.com>");
MODULE_DESCRIPTION("Livepatch test: target module");
