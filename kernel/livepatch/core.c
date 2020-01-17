// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * core.c - Kernel Live Patching Core
 *
 * Copyright (C) 2014 Seth Jennings <sjenning@redhat.com>
 * Copyright (C) 2014 SUSE
 */

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/kmod.h>
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/list.h>
#include <linux/kallsyms.h>
#include <linux/livepatch.h>
#include <linux/elf.h>
#include <linux/moduleloader.h>
#include <linux/completion.h>
#include <linux/memory.h>
#include <linux/sched/clock.h>
#include <asm/cacheflush.h>
#include "core.h"
#include "patch.h"
#include "state.h"
#include "transition.h"

/*
 * klp_mutex is a coarse lock which serializes access to klp data.  All
 * accesses to klp-related variables and structures must have mutex protection,
 * except within the following functions which carefully avoid the need for it:
 *
 * - klp_ftrace_handler()
 * - klp_update_patch_state()
 */
DEFINE_MUTEX(klp_mutex);

/*
 * Actively used patches: enabled or in transition. Note that replaced
 * or disabled patches are not listed even though the related kernel
 * module still can be loaded.
 */
LIST_HEAD(klp_patches);

static struct kobject *klp_root_kobj;

static bool klp_is_module(struct klp_object *obj)
{
	return obj->name;
}

static bool klp_initialized(void)
{
	return !!klp_root_kobj;
}

static struct klp_func *klp_find_func(struct klp_object *obj,
				      struct klp_func *old_func)
{
	struct klp_func *func;

	klp_for_each_func(obj, func) {
		if ((strcmp(old_func->old_name, func->old_name) == 0) &&
		    (old_func->old_sympos == func->old_sympos)) {
			return func;
		}
	}

	return NULL;
}

static struct klp_object *klp_find_object(struct klp_patch *patch,
					  struct klp_object *old_obj)
{
	struct klp_object *obj;

	klp_for_each_object(patch, obj) {
		if (klp_is_module(old_obj)) {
			if (klp_is_module(obj) &&
			    strcmp(old_obj->name, obj->name) == 0) {
				return obj;
			}
		} else if (!klp_is_module(obj)) {
			return obj;
		}
	}

	return NULL;
}

static struct klp_patch *klp_find_patch(const char *patch_name)
{
	struct klp_patch *patch;

	klp_for_each_patch(patch) {
		if (!strcmp(patch->obj->patch_name, patch_name))
			return patch;
	}

	return NULL;
}

/*
 * Search whether livepatch for a module is loaded.
 * Do not use for "vmlinux" that is always loaded.
 * Must be called under klp_mutex.
 */
static bool klp_is_object_loaded(struct klp_patch *patch,
				 char *object_name)
{
	struct klp_object *obj;

	klp_for_each_object(patch, obj) {
		if (obj->name && !strcmp(object_name, obj->name))
			return true;
	}

	return false;
}

struct klp_find_arg {
	const char *objname;
	const char *name;
	unsigned long addr;
	unsigned long count;
	unsigned long pos;
};

static int klp_find_callback(void *data, const char *name,
			     struct module *mod, unsigned long addr)
{
	struct klp_find_arg *args = data;

	if ((mod && !args->objname) || (!mod && args->objname))
		return 0;

	if (strcmp(args->name, name))
		return 0;

	if (args->objname && strcmp(args->objname, mod->name))
		return 0;

	args->addr = addr;
	args->count++;

	/*
	 * Finish the search when the symbol is found for the desired position
	 * or the position is not defined for a non-unique symbol.
	 */
	if ((args->pos && (args->count == args->pos)) ||
	    (!args->pos && (args->count > 1)))
		return 1;

	return 0;
}

static int klp_find_object_symbol(const char *objname, const char *name,
				  unsigned long sympos, unsigned long *addr)
{
	struct klp_find_arg args = {
		.objname = objname,
		.name = name,
		.addr = 0,
		.count = 0,
		.pos = sympos,
	};

	mutex_lock(&module_mutex);
	if (objname)
		module_kallsyms_on_each_symbol(klp_find_callback, &args);
	else
		kallsyms_on_each_symbol(klp_find_callback, &args);
	mutex_unlock(&module_mutex);

	/*
	 * Ensure an address was found. If sympos is 0, ensure symbol is unique;
	 * otherwise ensure the symbol position count matches sympos.
	 */
	if (args.addr == 0)
		pr_err("symbol '%s' not found in symbol table\n", name);
	else if (args.count > 1 && sympos == 0) {
		pr_err("unresolvable ambiguity for symbol '%s' in object '%s'\n",
		       name, objname);
	} else if (sympos != args.count && sympos > 0) {
		pr_err("symbol position %lu for symbol '%s' in object '%s' not found\n",
		       sympos, name, objname ? objname : "vmlinux");
	} else {
		*addr = args.addr;
		return 0;
	}

	*addr = 0;
	return -EINVAL;
}

static int klp_resolve_symbols(Elf_Shdr *relasec, struct module *pmod)
{
	int i, cnt, vmlinux, ret;
	char objname[MODULE_NAME_LEN];
	char symname[KSYM_NAME_LEN];
	char *strtab = pmod->core_kallsyms.strtab;
	Elf_Rela *relas;
	Elf_Sym *sym;
	unsigned long sympos, addr;

	/*
	 * Since the field widths for objname and symname in the sscanf()
	 * call are hard-coded and correspond to MODULE_NAME_LEN and
	 * KSYM_NAME_LEN respectively, we must make sure that MODULE_NAME_LEN
	 * and KSYM_NAME_LEN have the values we expect them to have.
	 *
	 * Because the value of MODULE_NAME_LEN can differ among architectures,
	 * we use the smallest/strictest upper bound possible (56, based on
	 * the current definition of MODULE_NAME_LEN) to prevent overflows.
	 */
	BUILD_BUG_ON(MODULE_NAME_LEN < 56 || KSYM_NAME_LEN != 128);

	relas = (Elf_Rela *) relasec->sh_addr;
	/* For each rela in this klp relocation section */
	for (i = 0; i < relasec->sh_size / sizeof(Elf_Rela); i++) {
		sym = pmod->core_kallsyms.symtab + ELF_R_SYM(relas[i].r_info);
		if (sym->st_shndx != SHN_LIVEPATCH) {
			pr_err("symbol %s is not marked as a livepatch symbol\n",
			       strtab + sym->st_name);
			return -EINVAL;
		}

		/* Format: .klp.sym.objname.symname,sympos */
		cnt = sscanf(strtab + sym->st_name,
			     ".klp.sym.%55[^.].%127[^,],%lu",
			     objname, symname, &sympos);
		if (cnt != 3) {
			pr_err("symbol %s has an incorrectly formatted name\n",
			       strtab + sym->st_name);
			return -EINVAL;
		}

		/* klp_find_object_symbol() treats a NULL objname as vmlinux */
		vmlinux = !strcmp(objname, "vmlinux");
		ret = klp_find_object_symbol(vmlinux ? NULL : objname,
					     symname, sympos, &addr);
		if (ret)
			return ret;

		sym->st_value = addr;
	}

	return 0;
}

static int klp_write_object_relocations(struct klp_object *obj)
{
	int i, cnt, ret = 0;
	const char *objname, *secname;
	char sec_objname[MODULE_NAME_LEN];
	struct module *pmod;
	Elf_Shdr *sec;

	objname = klp_is_module(obj) ? obj->name : "vmlinux";
	pmod = obj->mod;

	/* For each klp relocation section */
	for (i = 1; i < pmod->klp_info->hdr.e_shnum; i++) {
		sec = pmod->klp_info->sechdrs + i;
		secname = pmod->klp_info->secstrings + sec->sh_name;
		if (!(sec->sh_flags & SHF_RELA_LIVEPATCH))
			continue;

		/*
		 * Format: .klp.rela.sec_objname.section_name
		 * See comment in klp_resolve_symbols() for an explanation
		 * of the selected field width value.
		 */
		cnt = sscanf(secname, ".klp.rela.%55[^.]", sec_objname);
		if (cnt != 1) {
			pr_err("section %s has an incorrectly formatted name\n",
			       secname);
			ret = -EINVAL;
			break;
		}

		if (strcmp(objname, sec_objname))
			continue;

		ret = klp_resolve_symbols(sec, pmod);
		if (ret)
			break;

		ret = apply_relocate_add(pmod->klp_info->sechdrs,
					 pmod->core_kallsyms.strtab,
					 pmod->klp_info->symndx, i, pmod);
		if (ret)
			break;
	}

	return ret;
}

/*
 * Sysfs Interface
 *
 * /sys/kernel/livepatch
 * /sys/kernel/livepatch/<patch>
 * /sys/kernel/livepatch/<patch>/enabled
 * /sys/kernel/livepatch/<patch>/transition
 * /sys/kernel/livepatch/<patch>/force
 * /sys/kernel/livepatch/<patch>/<object>
 * /sys/kernel/livepatch/<patch>/<object>/<function,sympos>
 */
static int __klp_disable_patch(struct klp_patch *patch);

static ssize_t enabled_store(struct kobject *kobj, struct kobj_attribute *attr,
			     const char *buf, size_t count)
{
	struct klp_patch *patch;
	int ret;
	bool enabled;

	ret = kstrtobool(buf, &enabled);
	if (ret)
		return ret;

	patch = container_of(kobj, struct klp_patch, kobj);

	mutex_lock(&klp_mutex);

	if (patch->enabled == enabled) {
		/* already in requested state */
		ret = -EINVAL;
		goto out;
	}

	/*
	 * Allow to reverse a pending transition in both ways. It might be
	 * necessary to complete the transition without forcing and breaking
	 * the system integrity.
	 *
	 * Do not allow to re-enable a disabled patch.
	 */
	if (patch == klp_transition_patch)
		klp_reverse_transition();
	else if (!enabled)
		ret = __klp_disable_patch(patch);
	else
		ret = -EINVAL;

out:
	mutex_unlock(&klp_mutex);

	if (ret)
		return ret;
	return count;
}

static ssize_t enabled_show(struct kobject *kobj,
			    struct kobj_attribute *attr, char *buf)
{
	struct klp_patch *patch;

	patch = container_of(kobj, struct klp_patch, kobj);
	return snprintf(buf, PAGE_SIZE-1, "%d\n", patch->enabled);
}

static ssize_t transition_show(struct kobject *kobj,
			       struct kobj_attribute *attr, char *buf)
{
	struct klp_patch *patch;

	patch = container_of(kobj, struct klp_patch, kobj);
	return snprintf(buf, PAGE_SIZE-1, "%d\n",
			patch == klp_transition_patch);
}

static ssize_t force_store(struct kobject *kobj, struct kobj_attribute *attr,
			   const char *buf, size_t count)
{
	struct klp_patch *patch;
	int ret;
	bool val;

	ret = kstrtobool(buf, &val);
	if (ret)
		return ret;

	if (!val)
		return count;

	mutex_lock(&klp_mutex);

	patch = container_of(kobj, struct klp_patch, kobj);
	if (patch != klp_transition_patch) {
		mutex_unlock(&klp_mutex);
		return -EINVAL;
	}

	klp_force_transition();

	mutex_unlock(&klp_mutex);

	return count;
}

static struct kobj_attribute enabled_kobj_attr = __ATTR_RW(enabled);
static struct kobj_attribute transition_kobj_attr = __ATTR_RO(transition);
static struct kobj_attribute force_kobj_attr = __ATTR_WO(force);
static struct attribute *klp_patch_attrs[] = {
	&enabled_kobj_attr.attr,
	&transition_kobj_attr.attr,
	&force_kobj_attr.attr,
	NULL
};
ATTRIBUTE_GROUPS(klp_patch);

static void klp_free_object_dynamic(struct klp_object *obj)
{
	kfree(obj->name);
	kfree(obj);
}

static void klp_init_func_early(struct klp_object *obj,
				struct klp_func *func);
static int klp_init_object_early(struct klp_patch *patch,
				 struct klp_object *obj);

static struct klp_object *klp_alloc_object_dynamic(const char *name,
						   struct klp_patch *patch)
{
	struct klp_object *obj;

	obj = kzalloc(sizeof(*obj), GFP_KERNEL);
	if (!obj)
		return NULL;

	if (name) {
		obj->name = kstrdup(name, GFP_KERNEL);
		if (!obj->name) {
			kfree(obj);
			return NULL;
		}
	}

	klp_init_object_early(patch, obj);
	obj->dynamic = true;

	return obj;
}

static void klp_free_func_nop(struct klp_func *func)
{
	kfree(func->old_name);
	kfree(func);
}

static struct klp_func *klp_alloc_func_nop(struct klp_func *old_func,
					   struct klp_object *obj)
{
	struct klp_func *func;

	func = kzalloc(sizeof(*func), GFP_KERNEL);
	if (!func)
		return NULL;

	if (old_func->old_name) {
		func->old_name = kstrdup(old_func->old_name, GFP_KERNEL);
		if (!func->old_name) {
			kfree(func);
			return NULL;
		}
	}

	klp_init_func_early(obj, func);
	/*
	 * func->new_func is same as func->old_func. These addresses are
	 * set when the object is loaded, see klp_init_object_loaded().
	 */
	func->old_sympos = old_func->old_sympos;
	func->nop = true;

	return func;
}

static int klp_add_object_nops(struct klp_patch *patch,
			       struct klp_object *old_obj)
{
	struct klp_object *obj;
	struct klp_func *func, *old_func;

	obj = klp_find_object(patch, old_obj);

	if (!obj) {
		obj = klp_alloc_object_dynamic(old_obj->name, patch);
		if (!obj)
			return -ENOMEM;
	}

	klp_for_each_func(old_obj, old_func) {
		func = klp_find_func(obj, old_func);
		if (func)
			continue;

		func = klp_alloc_func_nop(old_func, obj);
		if (!func)
			return -ENOMEM;
	}

	return 0;
}

/*
 * Add 'nop' functions which simply return to the caller to run
 * the original function. The 'nop' functions are added to a
 * patch to facilitate a 'replace' mode.
 */
static int klp_add_nops(struct klp_patch *patch)
{
	struct klp_patch *old_patch;
	struct klp_object *old_obj;

	klp_for_each_patch(old_patch) {
		klp_for_each_object(old_patch, old_obj) {
			int err;

			err = klp_add_object_nops(patch, old_obj);
			if (err)
				return err;
		}
	}

	return 0;
}

static void klp_kobj_release_patch(struct kobject *kobj)
{
	struct klp_patch *patch;

	patch = container_of(kobj, struct klp_patch, kobj);
	complete(&patch->finish);
}

static struct kobj_type klp_ktype_patch = {
	.release = klp_kobj_release_patch,
	.sysfs_ops = &kobj_sysfs_ops,
	.default_groups = klp_patch_groups,
};

static void klp_kobj_release_object(struct kobject *kobj)
{
	struct klp_object *obj;

	obj = container_of(kobj, struct klp_object, kobj);

	if (obj->dynamic) {
		klp_free_object_dynamic(obj);
		return;
	}

	if (klp_is_module(obj) && !obj->forced)
		module_put(obj->mod);
}

static struct kobj_type klp_ktype_object = {
	.release = klp_kobj_release_object,
	.sysfs_ops = &kobj_sysfs_ops,
};

static void klp_kobj_release_func(struct kobject *kobj)
{
	struct klp_func *func;

	func = container_of(kobj, struct klp_func, kobj);

	if (func->nop)
		klp_free_func_nop(func);
}

static struct kobj_type klp_ktype_func = {
	.release = klp_kobj_release_func,
	.sysfs_ops = &kobj_sysfs_ops,
};

static void __klp_free_funcs(struct klp_object *obj, bool nops_only)
{
	struct klp_func *func, *tmp_func;

	klp_for_each_func_safe(obj, func, tmp_func) {
		if (nops_only && !func->nop)
			continue;

		list_del(&func->node);
		kobject_put(&func->kobj);
	}
}

/* Clean up when a patched object is unloaded */
static void klp_free_object_loaded(struct klp_object *obj)
{
	struct klp_func *func;

	obj->mod = NULL;

	klp_for_each_func(obj, func) {
		func->old_func = NULL;

		if (func->nop)
			func->new_func = NULL;
	}
}

static void klp_free_object(struct klp_object *obj, bool nops_only)
{
	__klp_free_funcs(obj, nops_only);

	if (nops_only && !obj->dynamic)
		return;

	list_del(&obj->node);
	kobject_put(&obj->kobj);
}

static void __klp_free_objects(struct klp_patch *patch, bool nops_only)
{
	struct klp_object *obj, *tmp_obj;

	klp_for_each_object_safe(patch, obj, tmp_obj) {
		klp_free_object(obj, nops_only);
	}
}

static void klp_free_objects(struct klp_patch *patch)
{
	__klp_free_objects(patch, false);
}

static void klp_free_objects_dynamic(struct klp_patch *patch)
{
	__klp_free_objects(patch, true);
}

/*
 * This function implements the free operations that can be called safely
 * under klp_mutex.
 *
 * The operation must be completed by calling klp_free_patch_finish()
 * outside klp_mutex.
 */
static void klp_free_patch_start(struct klp_patch *patch)
{
	if (!list_empty(&patch->list))
		list_del(&patch->list);

	klp_free_objects(patch);
}

/*
 * This function implements the free part that must be called outside
 * klp_mutex.
 *
 * It must be called after klp_free_patch_start(). And it has to be
 * the last function accessing the livepatch structures when the patch
 * gets disabled.
 */
static void klp_free_patch_finish(struct klp_patch *patch)
{
	/*
	 * Avoid deadlock with enabled_store() sysfs callback by
	 * calling this outside klp_mutex. It is safe because
	 * this is called when the patch gets disabled and it
	 * cannot get enabled again.
	 */
	kobject_put(&patch->kobj);
	wait_for_completion(&patch->finish);

	/* Put the module after the last access to struct klp_patch. */
	if (!patch->obj->forced)
		module_put(patch->obj->mod);
}

/*
 * The livepatch might be freed from sysfs interface created by the patch.
 * This work allows to wait until the interface is destroyed in a separate
 * context.
 */
static void klp_free_patch_work_fn(struct work_struct *work)
{
	struct klp_patch *patch =
		container_of(work, struct klp_patch, free_work);

	klp_free_patch_finish(patch);
}

void klp_free_patch_async(struct klp_patch *patch)
{
	klp_free_patch_start(patch);
	schedule_work(&patch->free_work);
}

void klp_free_replaced_patches_async(struct klp_patch *new_patch)
{
	struct klp_patch *old_patch, *tmp_patch;

	klp_for_each_patch_safe(old_patch, tmp_patch) {
		if (old_patch == new_patch)
			return;
		klp_free_patch_async(old_patch);
	}
}

static int klp_init_func(struct klp_object *obj, struct klp_func *func)
{
	if (!func->old_name)
		return -EINVAL;

	/*
	 * NOPs get the address later. The patched module must be loaded,
	 * see klp_init_object_loaded().
	 */
	if (!func->new_func && !func->nop)
		return -EINVAL;

	if (strlen(func->old_name) >= KSYM_NAME_LEN)
		return -EINVAL;

	INIT_LIST_HEAD(&func->stack_node);
	func->patched = false;
	func->transition = false;

	/* The format for the sysfs directory is <function,sympos> where sympos
	 * is the nth occurrence of this symbol in kallsyms for the patched
	 * object. If the user selects 0 for old_sympos, then 1 will be used
	 * since a unique symbol will be the first occurrence.
	 */
	return kobject_add(&func->kobj, &obj->kobj, "%s,%lu",
			   func->old_name,
			   func->old_sympos ? func->old_sympos : 1);
}

/* Arches may override this to finish any remaining arch-specific tasks */
void __weak arch_klp_init_object_loaded(struct klp_object *obj)
{
}

/* parts of the initialization that is done only when the object is loaded */
static int klp_init_object_loaded(struct klp_object *obj)
{
	struct klp_func *func;
	int ret;

	mutex_lock(&text_mutex);

	module_disable_ro(obj->mod);
	ret = klp_write_object_relocations(obj);
	if (ret) {
		module_enable_ro(obj->mod, true);
		mutex_unlock(&text_mutex);
		return ret;
	}

	arch_klp_init_object_loaded(obj);
	module_enable_ro(obj->mod, true);

	mutex_unlock(&text_mutex);

	klp_for_each_func(obj, func) {
		ret = klp_find_object_symbol(obj->name, func->old_name,
					     func->old_sympos,
					     (unsigned long *)&func->old_func);
		if (ret)
			return ret;

		ret = kallsyms_lookup_size_offset((unsigned long)func->old_func,
						  &func->old_size, NULL);
		if (!ret) {
			pr_err("kallsyms size lookup failed for '%s'\n",
			       func->old_name);
			return -ENOENT;
		}

		if (func->nop)
			func->new_func = func->old_func;

		ret = kallsyms_lookup_size_offset((unsigned long)func->new_func,
						  &func->new_size, NULL);
		if (!ret) {
			pr_err("kallsyms size lookup failed for '%s' replacement\n",
			       func->old_name);
			return -ENOENT;
		}
	}

	return 0;
}

static int klp_init_object(struct klp_patch *patch, struct klp_object *obj)
{
	struct klp_func *func;
	int ret;
	const char *name;

	obj->patched = false;

	name = obj->name ? obj->name : "vmlinux";
	ret = kobject_add(&obj->kobj, &patch->kobj, "%s", name);
	if (ret)
		return ret;

	klp_for_each_func(obj, func) {
		ret = klp_init_func(obj, func);
		if (ret)
			return ret;
	}

	ret = klp_init_object_loaded(obj);

	return ret;
}

static void klp_init_func_early(struct klp_object *obj,
				struct klp_func *func)
{
	kobject_init(&func->kobj, &klp_ktype_func);
	list_add_tail(&func->node, &obj->func_list);
}

static int klp_init_object_early(struct klp_patch *patch,
				  struct klp_object *obj)
{
	struct klp_func *func;

	if (!obj->funcs)
		return -EINVAL;

	INIT_LIST_HEAD(&obj->func_list);
	kobject_init(&obj->kobj, &klp_ktype_object);
	list_add_tail(&obj->node, &patch->obj_list);
	obj->forced = false;

	klp_for_each_func_static(obj, func) {
		klp_init_func_early(obj, func);
	}

	if (obj->dynamic || try_module_get(obj->mod))
		return 0;

	/* patch stays when this function fails in klp_add_object() */
	list_del(&obj->node);
	return -ENODEV;
}

static int klp_init_patch_early(struct klp_patch *patch)
{
	struct klp_object *obj = patch->obj;

	/* Main patch module is always for vmlinux */
	if (obj->name)
		return -EINVAL;

	INIT_LIST_HEAD(&patch->list);
	INIT_LIST_HEAD(&patch->obj_list);
	kobject_init(&patch->kobj, &klp_ktype_patch);
	patch->enabled = false;
	patch->ts = local_clock();
	INIT_WORK(&patch->free_work, klp_free_patch_work_fn);
	init_completion(&patch->finish);

	return klp_init_object_early(patch, obj);
}

static int klp_init_patch(struct klp_patch *patch)
{
	struct klp_object *obj;
	int ret;

	ret = kobject_add(&patch->kobj, klp_root_kobj, "%s", patch->obj->mod->name);
	if (ret)
		return ret;

	if (patch->replace) {
		ret = klp_add_nops(patch);
		if (ret)
			return ret;
	}

	klp_for_each_object(patch, obj) {
		ret = klp_init_object(patch, obj);
		if (ret)
			return ret;
	}

	list_add_tail(&patch->list, &klp_patches);

	return 0;
}

static int klp_check_module_name(struct klp_object *obj, bool is_module)
{
	char mod_name[MODULE_NAME_LEN];
	const char *expected_name;

	if (is_module) {
		snprintf(mod_name, sizeof(mod_name), "%s__%s",
			 obj->patch_name, obj->name);
		expected_name = mod_name;
	} else {
		expected_name = obj->patch_name;
	}

	if (strcmp(expected_name, obj->mod->name)) {
		pr_err("The module name %s does not match with obj->patch_name and obj->name. The expected name is: %s\n",
		       obj->mod->name, expected_name);
		return -EINVAL;
	}

	return 0;
}

static int klp_check_object(struct klp_object *obj, bool is_module)
{

	if (!obj->mod)
		return -EINVAL;

	if (!is_livepatch_module(obj->mod)) {
		pr_err("module %s is not marked as a livepatch module\n",
		       obj->mod->name);
		return -EINVAL;
	}

	if (!obj->patch_name) {
		pr_err("module %s does not have set obj->patch_name\n",
		       obj->mod->name);
		return -EINVAL;
	}

	if (strlen(obj->patch_name) >= MODULE_NAME_LEN) {
		pr_err("module %s has too long obj->patch_name\n",
		       obj->mod->name);
		return -EINVAL;
	}

	if (is_module) {
		if (!obj->name) {
			pr_err("module %s does not have set obj->name\n",
			       obj->mod->name);
			return -EINVAL;
		}
		if (strlen(obj->name) >= MODULE_NAME_LEN) {
			pr_err("module %s has too long obj->name\n",
			       obj->mod->name);
			return -EINVAL;
		}
	} else if (obj->name) {
		pr_err("module %s for vmlinux must not have set obj->name\n",
		       obj->mod->name);
		return -EINVAL;
	}

	if (!obj->funcs) {
		pr_err("module %s does not have set obj->funcs\n",
		       obj->mod->name);
		return -EINVAL;
	}

	return klp_check_module_name(obj, is_module);
}

static bool klp_is_object_name_supported(struct klp_patch *patch,
					 const char *name)
{
	int i;

	for (i = 0; patch->obj_names[i]; i++) {
		if (!strcmp(name, patch->obj_names[i]))
			return true;
	}

	return false;
}

/* Must be called under klp_mutex */
static bool klp_is_object_compatible(struct klp_patch *patch,
				     struct klp_object *obj)
{
	struct module *patched_mod;

	if (!klp_is_object_name_supported(patch, obj->name)) {
		pr_err("Livepatch (%s) is not supposed to livepatch the module: %s\n",
		       obj->patch_name, obj->name);
		return false;
	}

	mutex_lock(&module_mutex);
	patched_mod = find_module(obj->name);
	mutex_unlock(&module_mutex);

	if (!patched_mod) {
		pr_err("Livepatched module is not loaded: %s\n", obj->name);
		return false;
	}

	return true;
}

int klp_add_object(struct klp_object *obj)
{
	struct klp_patch *patch;
	int ret;

	ret = klp_check_object(obj, true);
	if (ret)
		return ret;

	mutex_lock(&klp_mutex);

	patch = klp_find_patch(obj->patch_name);
	if (!patch) {
		pr_err("Can't load livepatch (%s) for module when the livepatch (%s) for vmcore is not loaded\n",
		       obj->mod->name, obj->patch_name);
		ret = -EINVAL;
		goto err;
	}

	if (!klp_is_object_compatible(patch, obj)) {
		ret = -EINVAL;
		goto err;
	}

	ret = klp_init_object_early(patch, obj);
	if (ret)
		goto err;

	ret = klp_init_object(patch, obj);
	if (ret) {
		pr_warn("failed to initialize patch '%s' for module '%s' (%d)\n",
			patch->obj->patch_name, obj->name, ret);
		goto err_free;
	}

	pr_notice("applying patch '%s' to loading module '%s'\n",
		  patch->obj->patch_name, obj->name);

	ret = klp_pre_patch_callback(obj);
	if (ret) {
		pr_warn("pre-patch callback failed for object '%s'\n",
			obj->name);
		goto err_free;
	}

	ret = klp_patch_object(obj);
	if (ret) {
		pr_warn("failed to apply patch '%s' to module '%s' (%d)\n",
			patch->obj->patch_name, obj->name, ret);

		klp_post_unpatch_callback(obj);
		goto err_free;
	}

	if (patch != klp_transition_patch)
		klp_post_patch_callback(obj);

	mutex_unlock(&klp_mutex);
	return 0;

err_free:
	klp_free_object(obj, false);
err:
	/*
	 * If a patch is unsuccessfully applied, return
	 * error to the module loader.
	 */
	pr_warn("patch '%s' failed for module '%s', refusing to load module '%s'\n",
		patch->obj->patch_name, obj->name, obj->name);
	mutex_unlock(&klp_mutex);
	return ret;
}
EXPORT_SYMBOL_GPL(klp_add_object);

static int __klp_disable_patch(struct klp_patch *patch)
{
	struct klp_object *obj;

	if (WARN_ON(!patch->enabled))
		return -EINVAL;

	if (klp_transition_patch)
		return -EBUSY;

	klp_init_transition(patch, KLP_UNPATCHED);

	klp_for_each_object(patch, obj)
		if (obj->patched)
			klp_pre_unpatch_callback(obj);

	/*
	 * Enforce the order of the func->transition writes in
	 * klp_init_transition() and the TIF_PATCH_PENDING writes in
	 * klp_start_transition().  In the rare case where klp_ftrace_handler()
	 * is called shortly after klp_update_patch_state() switches the task,
	 * this ensures the handler sees that func->transition is set.
	 */
	smp_wmb();

	klp_start_transition();
	patch->enabled = false;
	klp_try_complete_transition();

	return 0;
}

static int klp_try_load_object(const char *patch_name, const char *obj_name)
{
	int ret;

	ret = request_module("%s__%s", patch_name, obj_name);
	if (ret) {
		/* modprobe always set exit code 1 on error */
		if (ret > 0)
			ret = -EINVAL;
		pr_info("Module load failed: %s__%s\n", patch_name, obj_name);
		return ret;
	}

	return 0;
}

static int __klp_enable_patch(struct klp_patch *patch)
{
	struct klp_object *obj;
	int ret;

	if (klp_transition_patch)
		return -EBUSY;

	if (WARN_ON(patch->enabled))
		return -EINVAL;

	pr_notice("enabling patch '%s'\n", patch->obj->patch_name);

	klp_init_transition(patch, KLP_PATCHED);

	/*
	 * Enforce the order of the func->transition writes in
	 * klp_init_transition() and the ops->func_stack writes in
	 * klp_patch_object(), so that klp_ftrace_handler() will see the
	 * func->transition updates before the handler is registered and the
	 * new funcs become visible to the handler.
	 */
	smp_wmb();

	klp_for_each_object(patch, obj) {
		ret = klp_pre_patch_callback(obj);
		if (ret) {
			pr_warn("pre-patch callback failed for object '%s'\n",
				klp_is_module(obj) ? obj->name : "vmlinux");
			goto err;
		}

		ret = klp_patch_object(obj);
		if (ret) {
			pr_warn("failed to patch object '%s'\n",
				klp_is_module(obj) ? obj->name : "vmlinux");
			goto err;
		}
	}

	klp_start_transition();
	patch->enabled = true;
	klp_try_complete_transition();

	return 0;
err:
	pr_warn("failed to enable patch '%s'\n", patch->obj->patch_name);

	klp_cancel_transition();
	return ret;
}

/**
 * klp_enable_patch() - enable the livepatch
 * @patch:	patch to be enabled
 *
 * Initializes the data structure associated with the patch, creates the sysfs
 * interface, performs the needed symbol lookups and code relocations,
 * registers the patched functions with ftrace.
 *
 * This function is supposed to be called from the livepatch module_init()
 * callback.
 *
 * Return: 0 on success, otherwise error
 */
int klp_enable_patch(struct klp_patch *patch)
{
	int ret;

	if (!patch || !patch->obj || !patch->obj_names)
		return -EINVAL;

	ret = klp_check_object(patch->obj, false);
	if (ret)
		return ret;

	if (!klp_initialized())
		return -ENODEV;

	if (!klp_have_reliable_stack()) {
		pr_warn("This architecture doesn't have support for the livepatch consistency model.\n");
		pr_warn("The livepatch transition may never complete.\n");
	}

	mutex_lock(&klp_mutex);

	if (!klp_is_patch_compatible(patch)) {
		pr_err("Livepatch patch (%s) is not compatible with the already installed livepatches.\n",
			patch->obj->mod->name);
		mutex_unlock(&klp_mutex);
		return -EINVAL;
	}

	ret = klp_init_patch_early(patch);
	if (ret) {
		mutex_unlock(&klp_mutex);
		return ret;
	}

	ret = klp_init_patch(patch);
	if (ret)
		goto err;

	ret = __klp_enable_patch(patch);
	if (ret)
		goto err;

	mutex_unlock(&klp_mutex);

	return 0;

err:
	klp_free_patch_start(patch);

	mutex_unlock(&klp_mutex);

	klp_free_patch_finish(patch);

	return ret;
}
EXPORT_SYMBOL_GPL(klp_enable_patch);

/*
 * This function unpatches objects from the replaced livepatches.
 *
 * We could be pretty aggressive here. It is called in the situation where
 * these structures are no longer accessed from the ftrace handler.
 * All functions are redirected by the klp_transition_patch. They
 * use either a new code or they are in the original code because
 * of the special nop function patches.
 *
 * The only exception is when the transition was forced. In this case,
 * klp_ftrace_handler() might still see the replaced patch on the stack.
 * Fortunately, it is carefully designed to work with removed functions
 * thanks to RCU. We only have to keep the patches on the system. Also
 * this is handled transparently by patch->module_put.
 */
void klp_unpatch_replaced_patches(struct klp_patch *new_patch)
{
	struct klp_patch *old_patch;

	klp_for_each_patch(old_patch) {
		if (old_patch == new_patch)
			return;

		old_patch->enabled = false;
		klp_unpatch_objects(old_patch);
	}
}

/*
 * This function removes the dynamically allocated 'nop' functions.
 *
 * We could be pretty aggressive. NOPs do not change the existing
 * behavior except for adding unnecessary delay by the ftrace handler.
 *
 * It is safe even when the transition was forced. The ftrace handler
 * will see a valid ops->func_stack entry thanks to RCU.
 *
 * We could even free the NOPs structures. They must be the last entry
 * in ops->func_stack. Therefore unregister_ftrace_function() is called.
 * It does the same as klp_synchronize_transition() to make sure that
 * nobody is inside the ftrace handler once the operation finishes.
 *
 * IMPORTANT: It must be called right after removing the replaced patches!
 */
void klp_discard_nops(struct klp_patch *new_patch)
{
	klp_unpatch_objects_dynamic(klp_transition_patch);
	klp_free_objects_dynamic(klp_transition_patch);
}

/*
 * Remove parts of patches that touch a given kernel module. The list of
 * patches processed might be limited. When limit is NULL, all patches
 * will be handled.
 */
static void klp_cleanup_module_patches_limited(struct module *mod,
					       struct klp_patch *limit)
{
	struct klp_patch *patch;
	struct klp_object *obj;

	klp_for_each_patch(patch) {
		if (patch == limit)
			break;

		klp_for_each_object(patch, obj) {
			if (!klp_is_module(obj) || strcmp(obj->name, mod->name))
				continue;

			if (patch != klp_transition_patch)
				klp_pre_unpatch_callback(obj);

			pr_notice("reverting patch '%s' on unloading module '%s'\n",
				  patch->obj->patch_name, obj->name);
			klp_unpatch_object(obj);

			klp_post_unpatch_callback(obj);

			klp_free_object_loaded(obj);
			break;
		}
	}
}

int klp_module_coming(struct module *mod)
{
	char patch_name[MODULE_NAME_LEN];
	struct klp_patch *patch;
	u64 patch_ts;
	int ret = 0;

	if (WARN_ON(mod->state != MODULE_STATE_COMING))
		return -EINVAL;

	mutex_lock(&klp_mutex);
restart:
	klp_for_each_patch(patch) {
		if (!klp_is_object_name_supported(patch, mod->name))
			continue;

		if (klp_is_object_loaded(patch, mod->name))
			continue;

		strncpy(patch_name, patch->obj->patch_name, sizeof(patch_name));
		patch_ts = patch->ts;
		mutex_unlock(&klp_mutex);

		ret = klp_try_load_object(patch_name, mod->name);
		/*
		 * The load might have failed because the patch has
		 * been removed in the meantime. In this case, the
		 * error might be ignored.
		 */
		mutex_lock(&klp_mutex);
		if (ret) {
			patch = klp_find_patch(patch_name);
			if (patch && patch->ts == patch_ts)
				goto err;
			ret = 0;
		}

		/*
		 * The list of patches might have been manipulated
		 * in the meantime.
		 */
		goto restart;
	}

	/*
	 * All enabled livepatches are loaded now. From this point, any newly
	 * enabled livepatch is responsible for loading the related livepatch
	 * module in klp_enable_patch().
	 */
	mod->klp_alive = true;
err:
	mutex_unlock(&klp_mutex);
	return ret;
}

void klp_module_going(struct module *mod)
{
	if (WARN_ON(mod->state != MODULE_STATE_GOING &&
		    mod->state != MODULE_STATE_COMING))
		return;

	mutex_lock(&klp_mutex);
	/*
	 * Each module has to know that klp_module_going()
	 * has been called. We never know what module will
	 * get patched by a new patch.
	 */
	mod->klp_alive = false;

	klp_cleanup_module_patches_limited(mod, NULL);

	mutex_unlock(&klp_mutex);
}

static int __init klp_init(void)
{
	klp_root_kobj = kobject_create_and_add("livepatch", kernel_kobj);
	if (!klp_root_kobj)
		return -ENOMEM;

	return 0;
}

module_init(klp_init);
