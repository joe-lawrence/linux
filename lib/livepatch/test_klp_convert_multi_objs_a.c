#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/livepatch.h>

void print_state_show_a(void);
void print_state_show_b(void);

/* klp-convert symbols - vmlinux */
extern void *state_show;

__used void print_state_show_a(void)
{
	pr_info("%s: state_show: %lx\n", __func__,
		(unsigned long) &state_show);
}

KLP_MODULE_RELOC(vmlinux) vmlinux_relocs_a[] = {
	KLP_SYMPOS(state_show, 1)
};

static struct klp_func funcs[] = {
	{
	}, { }
};

static struct klp_object objs[] = {
	{
		/* name being NULL means vmlinux */
		.funcs = funcs,
	}, { }
};

static struct klp_patch patch = {
	.mod = THIS_MODULE,
	.objs = objs,
};

static int test_klp_convert_init(void)
{
	int ret;

	ret = klp_enable_patch(&patch);
	if (ret)
		return ret;

	print_state_show_a();
	print_state_show_b();

	return 0;
}

static void test_klp_convert_exit(void)
{
}

module_init(test_klp_convert_init);
module_exit(test_klp_convert_exit);
MODULE_LICENSE("GPL");
MODULE_AUTHOR("Joe Lawrence <joe.lawrence@redhat.com>");
MODULE_DESCRIPTION("Livepatch test: klp-convert");
