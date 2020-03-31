// SPDX-License-Identifier: GPL-2.0
// Copyright (C) 2020 Joe Lawrence <joe.lawrence@redhat.com>

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/livepatch.h>
#include <asm/alternative.h>

/* TODO: find reliably true/false features */
/* TODO: other architectures? */
#define TRUE_FEATURE	(X86_FEATURE_FPU)
#define FALSE_FEATURE	(X86_FEATURE_VME)

extern void mod_function1(void);
extern void mod_function2(void);

__used static void klp_function1(void)
{
	pr_info("%s\n", __func__);
}

__used static void klp_function2(void)
{
	pr_info("%s\n", __func__);
}

static void klp_dump_info_msg(void)
{
	/*
 	 * FYI: Alternatives reference:
 	 *
 	 *                old (false) code,     new (true) code,     cpu feature
 	 */
	asm (ALTERNATIVE("call klp_function1", "call klp_function2", TRUE_FEATURE));
	asm (ALTERNATIVE("call klp_function1", "call klp_function2", FALSE_FEATURE));

	asm (ALTERNATIVE("call mod_function1", "call mod_function2", TRUE_FEATURE));
	asm (ALTERNATIVE("call mod_function1", "call mod_function2", FALSE_FEATURE));
	asm (ALTERNATIVE("call mod_function2", "call mod_function1", TRUE_FEATURE));
	asm (ALTERNATIVE("call mod_function2", "call mod_function1", FALSE_FEATURE));
}

static struct klp_func funcs[] = {
	{
		.old_name = "dump_info_msg",
		.new_func = klp_dump_info_msg,
	}, { }
};

static struct klp_object obj = {
	.patch_name = "test_klp_alt",
	.name = "test_klp_alt_mod",
	.mod = THIS_MODULE,
	.funcs = funcs,
};


extern void dump_info_msg(void);
static int test_klp_convert_alt_inst__alt_inst_mod_init(void)
{
	int ret;

	ret = klp_add_object(&obj);
	if (ret)
		return ret;

	dump_info_msg();

	return 0;
}

static void test_klp_convert_alt_inst__alt_inst_mod_exit(void)
{
}

module_init(test_klp_convert_alt_inst__alt_inst_mod_init);
module_exit(test_klp_convert_alt_inst__alt_inst_mod_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Joe Lawrence <joe.lawrence@redhat.com>");
MODULE_DESCRIPTION("Livepatch test: altinstructions");
MODULE_INFO(livepatch, "Y");
