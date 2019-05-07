#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/livepatch.h>

/* klp-convert symbols - vmlinux */
extern void *state_show;

__used void print_state_show_b(void)
{
	pr_info("%s: state_show: %lx\n", __func__,
		(unsigned long) &state_show);
}

KLP_MODULE_RELOC(vmlinux) vmlinux_relocs_b[] = {
	KLP_SYMPOS(state_show, 1)
};
