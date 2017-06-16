/*
 * shadow.c - Shadow Variables
 *
 * Copyright (C) 2014 Josh Poimboeuf <jpoimboe@redhat.com>
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

/*
 * Shadow variable API concurrency notes:
 * 
 * The shadow variable API simply provides a relationship between an
 * <obj, data> pair and a pointer value.  It is the responsibility of the
 * caller to provide any mutual exclusion required of the shadow data.
 * 
 * Once klp_shadow_attach() adds a shadow variable to the
 * klp_shadow_hash, it is considered live and klp_shadow_get() may
 * return the shadow variable's new_data pointer.  Therefore,
 * initialization of shadow new_data should be completed before
 * attaching the shadow variable.
 * 
 * If the API is called under a special context (like spinlocks), set
 * the GFP flags passed to klp_shadow_attach() accordingly.
 * 
 * The klp_shadow_hash is an RCU-enabled hashtable and should be safe
 * against concurrent klp_shadow_detach() and klp_shadow_get()
 * operations.
 * 
*/

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/hashtable.h>
#include <linux/slab.h>
#include <linux/livepatch.h>

static DEFINE_HASHTABLE(klp_shadow_hash, 12);
static DEFINE_SPINLOCK(klp_shadow_lock);

/**
 * shadow_match - verify a shadow variable matches given <obj, data>
 * @shadow:	shadow variable to match
 * @obj:	pointer to original data
 * @data:	numerical description of new data
 *
 * Returns true if the shadow variable matches.
 */
static inline bool shadow_match(struct klp_shadow *shadow, void *obj,
				unsigned long data)
{
	return shadow->obj == obj && shadow->data == data;
}

/**
 * _klp_shadow_add - add a new shadow variable
 * @obj:		pointer to original data
 * @data:		numerical description of new data
 * @new_data:		pointer to new data
 * @new_size:		size of new data
 * @gfp_flags:		GFP mask for allocation
 * @acquire_fn:		callback to acquire+init shadow variable storage
 *
 * Executes the acquire-callback to get storage for the new shadow variable
 * meta-data and new-data.
 *
 * Returns a pointer to new shadow variable.
 */
void *_klp_shadow_add(void *obj, unsigned long data, void *new_data,
		      size_t new_size, gfp_t gfp_flags,
		      klp_shadow_acquire_obj_func_t acquire_fn,
		      bool lock)
{
	struct klp_shadow *shadow;
	unsigned long flags;

	if (!acquire_fn)
		return NULL;

	shadow = acquire_fn(obj, data, new_data,
			    sizeof(*shadow) + new_size, gfp_flags);
	if (!shadow)
		return NULL;

	if (lock)
		spin_lock_irqsave(&klp_shadow_lock, flags);

	hash_add_rcu(klp_shadow_hash, &shadow->node, (unsigned long)obj);

	if (lock)
		spin_unlock_irqrestore(&klp_shadow_lock, flags);

	return shadow->new_data;
}

/**
 * klp_shadow_add - add a new shadow variable
 * @obj:		pointer to original data
 * @data:		numerical description of new data
 * @new_data:		pointer to new data
 * @new_size:		size of new data
 * @gfp_flags:		GFP mask for allocation
 * @acquire_fn:		callback to acquire+init shadow variable storage
 *
 * Executes the acquire-callback to get storage for the new shadow variable
 * meta-data and new-data.
 *
 * Returns a pointer to new shadow variable.
 */
void *klp_shadow_add(void *obj, unsigned long data, void *new_data,
		     size_t new_size, gfp_t gfp_flags,
		     klp_shadow_acquire_obj_func_t acquire_fn)
{
	return _klp_shadow_add(obj, data, new_data, new_size, gfp_flags,
			       acquire_fn, true);
}
EXPORT_SYMBOL_GPL(klp_shadow_add);

/**
 * shadow_alloc_cb - (callback) allocate and initialize new shadow variable
 * @obj:		pointer to original data
 * @data:		numerical description of new data
 * @new_data:		pointer to new data
 * @new_size:		size of shadow variable (including new data)
 * @gfp_flags:		GFP mask for allocation
 *
 * Returns a pointer to new shadow variable.
 */
static void *shadow_alloc_cb(void *obj, unsigned long data, void *new_data,
			     size_t new_size, gfp_t gfp_flags)
{
	struct klp_shadow *shadow;

	shadow = kzalloc(new_size, gfp_flags);
	if (shadow) {
		shadow->obj = obj;
		shadow->data = data;
		if (new_data) {
			memcpy(shadow->new_data, new_data,
			       new_size - sizeof(*shadow));
		}
	}

	return shadow;
}

/**
 * klp_shadow_attach - allocate and add a new shadow variable
 * @obj:	pointer to original data
 * @data:	numerical description of new data
 * @new_data:	pointer to new data
 * @new_size:   size of new data
 * @gfp_flags:	GFP mask used to allocate shadow variable metadata
 *
 * Returns the shadow variable new_data element, NULL on failure.
 */
void *klp_shadow_attach(void *obj, unsigned long data, void *new_data,
			size_t new_size, gfp_t gfp_flags)
{
	return klp_shadow_add(obj, data, new_data, new_size, gfp_flags,
			      shadow_alloc_cb);
}
EXPORT_SYMBOL_GPL(klp_shadow_attach);

/**
 * klp_shadow_get - retrieve a shadow variable new_data pointer
 * @obj:	pointer to original data
 * @data:	numerical description of new data
 *
 * Returns a pointer to shadow variable new data
 */
void *klp_shadow_get(void *obj, unsigned long data)
{
	struct klp_shadow *shadow;

	rcu_read_lock();

	hash_for_each_possible_rcu(klp_shadow_hash, shadow, node,
				   (unsigned long)obj) {

		if (shadow_match(shadow, obj, data)) {
			rcu_read_unlock();
			return shadow->new_data;
		}
	}

	rcu_read_unlock();

	return NULL;
}
EXPORT_SYMBOL_GPL(klp_shadow_get);

/**
 * klp_shadow_get_or_add - allocate and add a new shadow variable
 * @obj:	pointer to original data
 * @data:	numerical description of new data
 * @new_data:	pointer to new data
 * @new_size:   size of new data
 * @gfp_flags:	GFP mask used to allocate shadow variable metadata
 *
 * Returns the shadow variable new_data element, NULL on failure.
 */
void *klp_shadow_get_or_add(void *obj, unsigned long data, void *new_data,
			    size_t new_size, gfp_t gfp_flags,
			    klp_shadow_acquire_obj_func_t acquire_fn)
{
	void *nd;
	unsigned long flags;

	/* ??? WARN_ON(!flags & GFP_NOWAIT) ??? */

        nd = klp_shadow_get(obj, data);

        if (!nd && acquire_fn) {
                spin_lock_irqsave(&klp_shadow_lock, flags);
                nd = klp_shadow_get(obj, data);
                if (!nd) {
			nd = _klp_shadow_add(obj, data, new_data, new_size,
					     gfp_flags, acquire_fn, false);
		}
                spin_unlock_irqrestore(&klp_shadow_lock, flags);
        }

	return nd;
}
EXPORT_SYMBOL_GPL(klp_shadow_get_or_add);

/**
 * klp_shadow_get_or_attach - allocate and add a new shadow variable
 * @obj:	pointer to original data
 * @data:	numerical description of new data
 * @new_data:	pointer to new data
 * @new_size:   size of new data
 * @gfp_flags:	GFP mask used to allocate shadow variable metadata
 *
 * Returns the shadow variable new_data element, NULL on failure.
 */
void *klp_shadow_get_or_attach(void *obj, unsigned long data, void *new_data,
			       size_t new_size, gfp_t gfp_flags)
{
	return klp_shadow_get_or_add(obj, data, new_data, new_size, gfp_flags,
				     shadow_alloc_cb);
}
EXPORT_SYMBOL_GPL(klp_shadow_get_or_attach);

/**
 * klp_shadow_delete - delete <obj, data> shadow variable(s)
 * @obj:		pointer to original data (may be null to select <*, data>)
 * @data:		numerical description of new data
 * @shadow_retire_fn:	callback to release shadow variable
 *
 * Passing a non-NULL obj option will remote all <obj, data> matches (cleaning
 * up hash collisions on the same pair).
 *
 * Passing a NULL obj option will iterate through the entire hash, removing
 * any entry with a matching data.
 *
 * For each shadow variable removed from the hash, will execute the
 * retire-callback (under the klp_shadow_lock) to return shadow variable
 * storage.
 */
void klp_shadow_delete(void *obj, unsigned long data,
		       klp_shadow_retire_obj_func_t shadow_retire_fn)
{
	struct klp_shadow *shadow;
	unsigned long flags;
	int i;

	spin_lock_irqsave(&klp_shadow_lock, flags);

	if (obj) {

		/* Delete all <obj, data> from hash */
		hash_for_each_possible(klp_shadow_hash, shadow, node,
				       (unsigned long)obj) {

			if (shadow_match(shadow, obj, data)) {
				hash_del_rcu(&shadow->node);
				if (shadow_retire_fn)
					shadow_retire_fn(shadow);
			}
		}

	} else {

		/* Delete all <*, data> from hash */
		hash_for_each(klp_shadow_hash, i, shadow, node) {
			if (shadow_match(shadow, shadow->obj, data)) {
				hash_del_rcu(&shadow->node);
				if (shadow_retire_fn)
					shadow_retire_fn(shadow);
			}
		}
	}

	spin_unlock_irqrestore(&klp_shadow_lock, flags);
}
EXPORT_SYMBOL_GPL(klp_shadow_delete);

/**
 * shadow_free_cb - (callback) release a shadow variable
 * @shadow:	shadow variable to free
 */
static void shadow_free_cb(struct klp_shadow *shadow)
{
pr_info("klp: kfree @ %p\b", shadow);
	kfree_rcu(shadow, rcu_head);
}

/**
 * klp_shadow_delete_all - delete all <*, data> shadow variables
 * @obj:		pointer to original data
 * @data:		numerical description of new data
 * @shadow_retire_fn:	callback to release shadow variable
 */
void klp_shadow_delete_all(void *obj, unsigned long data,
			   klp_shadow_retire_obj_func_t shadow_retire_fn)
{
	 klp_shadow_delete(NULL, data, shadow_retire_fn);
}
EXPORT_SYMBOL_GPL(klp_shadow_delete_all);

/**
 * klp_shadow_detach - detach and free a <obj, data> shadow variable
 * @obj:		pointer to original data
 * @shadow_retire_fn:	callback to release shadow variable
 */
void klp_shadow_detach(void *obj, unsigned long data)
{
	 klp_shadow_delete(obj, data, shadow_free_cb);
}
EXPORT_SYMBOL_GPL(klp_shadow_detach);

/**
 * klp_shadow_detach_all - detach all <*, data> shadow variables
 * @data:	numerical description of new data
 */
void klp_shadow_detach_all(unsigned long data)
{
	 klp_shadow_delete(NULL, data, shadow_free_cb);
}
EXPORT_SYMBOL_GPL(klp_shadow_detach_all);
