/*
 * livepatch-hooks-demo.c - (un)patching hooks livepatch demo
 *
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

const char *module_state[] = {
	[MODULE_STATE_LIVE]	= "[MODULE_STATE_LIVE] Normal state",
	[MODULE_STATE_COMING]	= "[MODULE_STATE_COMING] Full formed, running module_init",
	[MODULE_STATE_GOING]	= "[MODULE_STATE_GOING] Going away",
	[MODULE_STATE_UNFORMED]	= "[MODULE_STATE_UNFORMED] Still setting it up",
};

static void hook_info(const char *hook, struct klp_object *obj)
{
	if (klp_is_module(obj))
		pr_info("%s: %s\n", hook, module_state[obj->mod->state]);
	else
		pr_info("%s: vmlinux\n", hook);
}

/* Executed on object patching (ie, patch enablement) */
static int patch_hook(struct klp_object *obj)
{
	hook_info(__func__, obj);
	return 0;
}

/* Executed on object unpatching (ie, patch disablement) */
static int unpatch_hook(struct klp_object *obj)
{
	hook_info(__func__, obj);
	return 0;
}

static struct klp_func funcs[] = {
	{ }
};

static struct klp_hook patch_hooks[] = {
	{
		.hook = patch_hook,
	}, { }
};
static struct klp_hook unpatch_hooks[] = {
	{
		.hook = unpatch_hook,
	}, { }
};

static struct klp_object objs[] = {
	{
		.name = "livepatch_hooks_mod",
		.funcs = funcs,
		.patch_hooks = patch_hooks,
		.unpatch_hooks = unpatch_hooks,
	}, { }
};

static struct klp_patch patch = {
	.mod = THIS_MODULE,
	.objs = objs,
};

static int livepatch_hooks_demo_init(void)
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

static void livepatch_hooks_demo_exit(void)
{
	WARN_ON(klp_unregister_patch(&patch));
}

module_init(livepatch_hooks_demo_init);
module_exit(livepatch_hooks_demo_exit);
MODULE_LICENSE("GPL");
MODULE_INFO(livepatch, "Y");
