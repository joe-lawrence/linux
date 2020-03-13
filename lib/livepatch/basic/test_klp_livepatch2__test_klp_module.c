// SPDX-License-Identifier: GPL-2.0
// Copyright (C) 2020 Joe Lawrence <joe.lawrence@redhat.com>

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/livepatch.h>

int livepatch_get_klp_module_status(char *buffer, const struct kernel_param *kp)
{
        return scnprintf(buffer, PAGE_SIZE, "%s: status: livepatched\n", THIS_MODULE->name);
}

static struct klp_func funcs[] = {
	{
		.old_name = "get_klp_module_status",
		.new_func = livepatch_get_klp_module_status,
	}, { }
};

struct klp_object obj = {
	.patch_name = "test_klp_livepatch2",
	.name = "test_klp_module",
	.mod = THIS_MODULE,
	.funcs = funcs,
};

static int test_klp_livepatch_init(void)
{
	return klp_add_object(&obj);
}

static void test_klp_livepatch_exit(void)
{
}

module_init(test_klp_livepatch_init);
module_exit(test_klp_livepatch_exit);
MODULE_LICENSE("GPL");
MODULE_INFO(livepatch, "Y");
MODULE_AUTHOR("Seth Jennings <sjenning@redhat.com>");
MODULE_DESCRIPTION("Livepatch test: livepatch module");
