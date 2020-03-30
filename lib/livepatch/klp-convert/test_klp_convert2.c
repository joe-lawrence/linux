// SPDX-License-Identifier: GPL-2.0
// Copyright (C) 2019 Joe Lawrence <joe.lawrence@redhat.com>

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/livepatch.h>

/* klp-convert symbols - vmlinux */
extern char *saved_command_line;

void print_saved_command_line(void)
{
	pr_info("saved_command_line (auto): %s\n", saved_command_line);
}

/*
 * saved_command_line is a uniquely named symbol, so the sympos
 * annotation is optional.  Skip it and test that klp-convert can
 * resolve the symbol on its own.
 */

static struct klp_func funcs[] = {
	{
	}, { }
};

static struct klp_object obj = {
	.patch_name = "test_klp_convert2",
	.name = NULL,   /* vmlinux */
	.mod = THIS_MODULE,
	.funcs = funcs,
};

static char *obj_names[] = {
	"test_klp_convert_mod",
	NULL
};

static struct klp_patch patch = {
	.obj = &obj,
	.obj_names = obj_names,
};

static int test_klp_convert_init(void)
{
	int ret;

	ret = klp_enable_patch(&patch);
	if (ret)
		return ret;

	print_saved_command_line();

	return 0;
}

static void test_klp_convert_exit(void)
{
}

module_init(test_klp_convert_init);
module_exit(test_klp_convert_exit);
MODULE_LICENSE("GPL");
MODULE_AUTHOR("Joe Lawrence <joe.lawrence@redhat.com>");
MODULE_DESCRIPTION("Livepatch test: klp-convert2");
MODULE_INFO(livepatch, "Y");
