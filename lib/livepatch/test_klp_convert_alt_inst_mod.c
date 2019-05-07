#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/livepatch.h>
#include <asm/alternative.h>

/* TODO: find reliably true/false features */
/* TODO: other architectures? */
#define TRUE_FEATURE	(X86_FEATURE_FPU)
#define FALSE_FEATURE	(X86_FEATURE_VME)

__used static void mod_function1(void)
{
	pr_info("%s\n", __func__);
}

__used static void mod_function2(void)
{
	pr_info("%s\n", __func__);
}

__used static void dump_info_msg(void)
{
	asm (ALTERNATIVE("call mod_function1", "call mod_function2", TRUE_FEATURE));
	asm (ALTERNATIVE("call mod_function1", "call mod_function2", FALSE_FEATURE));
}

static int test_klp_convert_alt_inst_mod_init(void)
{
	dump_info_msg();
	return 0;
}

static void test_klp_convert_alt_inst_mod_exit(void)
{
	dump_info_msg();
}

module_init(test_klp_convert_alt_inst_mod_init);
module_exit(test_klp_convert_alt_inst_mod_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Joe Lawrence <joe.lawrence@redhat.com>");
MODULE_DESCRIPTION("Livepatch test: altinstructions target module");
