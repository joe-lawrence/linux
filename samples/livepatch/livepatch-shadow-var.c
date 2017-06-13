/*
 * livepatch-shadow-var.c - Kernel Live Patching Sample Module
 *
 * Copyright (C) 2014 Seth Jennings <sjenning@redhat.com>
 * Copyright (C) 2017 Joe Lawrence <joe.lawrence@redhat.com>
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License
 * as published by the Free Software Foundation; either version 2
 * of the License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, see <http://www.gnu.org/licenses/>.
 */

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/livepatch.h>

/*
 * This (dumb) live patch overrides the function that prints the
 * kernel boot cmdline when /proc/cmdline is read.  It also
 * demonstrates a contrived shadow-variable usage.
 *
 * Example:
 *
 * $ cat /proc/cmdline
 * <your cmdline>
 * current=<current task pointer> count=<shadow variable counter>
 *
 * $ insmod livepatch-shadow-var.ko
 * $ cat /proc/cmdline
 * this has been live patched
 * current=ffff8800331c9540 count=1
 * $ cat /proc/cmdline
 * this has been live patched
 * current=ffff8800331c9540 count=2
 *
 * $ echo 0 > /sys/kernel/livepatch/livepatch_shadow_var/enabled
 * $ cat /proc/cmdline
 * <your cmdline>
 */

#define SV_TASK_CTR	(1)

static LIST_HEAD(shadow_list);

struct task_ctr {
	struct list_head list;
	int count;
};

#include <linux/seq_file.h>
#include <linux/slab.h>
static int livepatch_cmdline_proc_show(struct seq_file *m, void *v)
{
	struct task_ctr *ctr;

	ctr = klp_shadow_get(current, SV_TASK_CTR);
	if (!ctr) {
		ctr = kzalloc(sizeof(*ctr), GFP_KERNEL);
		if (ctr) {
			list_add(&ctr->list, &shadow_list);
			klp_shadow_attach(current, SV_TASK_CTR, GFP_KERNEL, ctr);
		}
	}

	seq_printf(m, "%s\n", "this has been live patched");

	if (ctr) {
		ctr->count++;
		seq_printf(m, "current=%p count=%d\n", current, ctr->count);
	}

	return 0;
}

static struct klp_func funcs[] = {
	{
		.old_name = "cmdline_proc_show",
		.new_func = livepatch_cmdline_proc_show,
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

static int livepatch_init(void)
{
	int ret;

	if (!klp_have_reliable_stack() && !patch.immediate) {
		/*
		 * WARNING: Be very careful when using 'patch.immediate' in
		 * your patches.  It's ok to use it for simple patches like
		 * this, but for more complex patches which change function
		 * semantics, locking semantics, or data structures, it may not
		 * be safe.  Use of this option will also prevent removal of
		 * the patch.
		 *
		 * See Documentation/livepatch/livepatch.txt for more details.
		 */
		patch.immediate = true;
		pr_notice("The consistency model isn't supported for your architecture.  Bypassing safety mechanisms and applying the patch immediately.\n");
	}

	ret = klp_register_patch(&patch);
	if (ret)
		return ret;
	ret = klp_enable_patch(&patch);
	if (ret) {
		WARN_ON(klp_unregister_patch(&patch));
		return ret;
	}
	return 0;
}

static void livepatch_exit(void)
{
	struct task_ctr *nd, *tmp;

	list_for_each_entry_safe(nd, tmp, &shadow_list, list) {
		list_del(&nd->list);
		kfree(nd);
	}
	WARN_ON(klp_unregister_patch(&patch));
}

module_init(livepatch_init);
module_exit(livepatch_exit);
MODULE_LICENSE("GPL");
MODULE_INFO(livepatch, "Y");
