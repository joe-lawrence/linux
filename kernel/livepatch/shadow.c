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

/**
 * DOC: Shadow variable API concurrency notes:
 *
 * The shadow variable API provides a simple relationship between an
 * <obj, id> pair and a pointer value.  It is the responsibility of the
 * caller to provide any mutual exclusion required of the shadow data.
 *
 * Once a shadow variable is "attached" to its parent object via the
 * klp_shadow_*attach() API calls, it is considered live: any subsequent
 * call to klp_shadow_get() may then return the shadow variable's data
 * pointer.  Callers of klp_shadow_*attach() should prepare shadow data
 * accordingly.
 *
 * The klp_shadow_*attach() API calls may allocate memory for new shadow
 * variable structures.  Their implementation does not call kmalloc
 * inside any spinlocks, but API callers should pass GFP flags according
 * to their specific needs.
 *
 * The klp_shadow_hash is an RCU-enabled hashtable and is safe against
 * concurrent klp_shadow_detach() and klp_shadow_get() operations.
 */

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/hashtable.h>
#include <linux/slab.h>
#include <linux/livepatch.h>

static DEFINE_HASHTABLE(klp_shadow_hash, 12);
static DEFINE_SPINLOCK(klp_shadow_lock);

/**
 * struct klp_shadow - shadow variable structure
 * @node:	klp_shadow_hash hash table node
 * @rcu_head:	RCU is used to safely free this structure
 * @obj:	pointer to parent object
 * @id:		data identifier
 * @data:	data area
 */
struct klp_shadow {
	struct hlist_node node;
	struct rcu_head rcu_head;
	void *obj;
	unsigned long id;
	char data[];
};

/**
 * shadow_match() - verify a shadow variable matches given <obj, id>
 * @shadow:	shadow variable to match
 * @obj:	pointer to parent object
 * @id:		data identifier
 *
 * Return: true if the shadow variable matches.
 */
static inline bool shadow_match(struct klp_shadow *shadow, void *obj,
				unsigned long id)
{
	return shadow->obj == obj && shadow->id == id;
}

/**
 * klp_shadow_get() - retrieve a shadow variable data pointer
 * @obj:	pointer to parent object
 * @id:		data identifier
 *
 * Return: the shadow variable data element, NULL on failure.
 */
void *klp_shadow_get(void *obj, unsigned long id)
{
	struct klp_shadow *shadow;

	rcu_read_lock();

	hash_for_each_possible_rcu(klp_shadow_hash, shadow, node,
				   (unsigned long)obj) {

		if (shadow_match(shadow, obj, id)) {
			rcu_read_unlock();
			return shadow->data;
		}
	}

	rcu_read_unlock();

	return NULL;
}
EXPORT_SYMBOL_GPL(klp_shadow_get);

/*
 * klp_shadow_set() - initialize a shadow variable
 * @shadow:	shadow variable to initialize
 * @obj:	pointer to parent object
 * @id:		data identifier
 * @data:	pointer to data to attach to parent
 * @size:	size of attached data
 */
static inline void klp_shadow_set(struct klp_shadow *shadow, void *obj,
				  unsigned long id, void *data, size_t size)
{
	shadow->obj = obj;
	shadow->id = id;

	if (data)
		memcpy(shadow->data, data, size);
}

/**
 * klp_shadow_add() - add a shadow variable to the hashtable
 * @shadow:	shadow variable to add
 */
static inline void klp_shadow_add(struct klp_shadow *shadow)
{
	hash_add_rcu(klp_shadow_hash, &shadow->node,
		     (unsigned long)shadow->obj);
}

/**
 * klp_shadow_attach() - allocate and add a new shadow variable
 * @obj:	pointer to parent object
 * @id:		data identifier
 * @data:	pointer to data to attach to parent
 * @size:	size of attached data
 * @gfp_flags:	GFP mask for allocation
 *
 * If an existing <obj, id> shadow variable can be found, this routine
 * will issue a WARN, exit early and return NULL.
 *
 * Allocates @size bytes for new shadow variable data using @gfp_flags
 * and copies @size bytes from @data into the new shadow variable's own
 * data space.  If @data is NULL, @size bytes are still allocated, but
 * no copy is performed.  The new shadow variable is then added to the
 * global hashtable.
 *
 * Return: the shadow variable data element, NULL on duplicate or
 * failure.
 */
void *klp_shadow_attach(void *obj, unsigned long id, void *data,
			size_t size, gfp_t gfp_flags)
{
	struct klp_shadow *new_shadow;
	void *shadow_data;
	unsigned long flags;

	/* Take error exit path if <obj, id> already exists */
	shadow_data = klp_shadow_get(obj, id);
	if (unlikely(shadow_data))
		goto err_exists;

	/* Allocate a new shadow variable for use inside the lock below */
	new_shadow = kzalloc(size + sizeof(*new_shadow), gfp_flags);
	if (!new_shadow)
		goto err;

	/* Look for <obj, id> again under the lock */
	spin_lock_irqsave(&klp_shadow_lock, flags);
	shadow_data = klp_shadow_get(obj, id);
	if (unlikely(shadow_data)) {

		/* Shadow variable found, throw away allocation and take
		 * error exit path */
		spin_unlock_irqrestore(&klp_shadow_lock, flags);
		kfree(shadow_data);
		goto err_exists;
	}

	/* No <obj, id> found, add the newly allocated one */
	shadow_data = data;
	klp_shadow_set(new_shadow, obj, id, data, size);
	klp_shadow_add(new_shadow);
	spin_unlock_irqrestore(&klp_shadow_lock, flags);

	return shadow_data;

err_exists:
	WARN(1, "Duplicate shadow variable <%p, %lx>\n", obj, id);
err:
	return NULL;
}
EXPORT_SYMBOL_GPL(klp_shadow_attach);

/**
 * klp_shadow_get_or_attach() - get existing or attach a new shadow variable
 * @obj:	pointer to parent object
 * @id:		data identifier
 * @data:	pointer to data to attach to parent
 * @size:	size of attached data
 * @gfp_flags:	GFP mask for allocation
 *
 * If an existing <obj, id> shadow variable can be found, it will be
 * used (but *not* updated) in the return value of this function.
 *
 * Allocates @size bytes for new shadow variable data using @gfp_flags
 * and copies @size bytes from @data into the new shadow variable's own
 * data space.  If @data is NULL, @size bytes are still allocated, but
 * no copy is performed.  The new shadow variable is then added to the
 * global hashtable.
 *
 * Return: the shadow variable data element, NULL on failure.
 */
void *klp_shadow_get_or_attach(void *obj, unsigned long id, void *data,
			       size_t size, gfp_t gfp_flags)
{
	struct klp_shadow *new_shadow;
	void *shadow_data;
	unsigned long flags;

	/* Return a shadow variable if <obj, id> already exists */
	shadow_data = klp_shadow_get(obj, id);
	if (shadow_data)
		goto ret;

	/* Allocate a new shadow variable for use inside the lock below */
	new_shadow = kzalloc(size + sizeof(*new_shadow), gfp_flags);
	if (!new_shadow)
		goto err;

	/* Look for <obj, id> again under the lock */
	spin_lock_irqsave(&klp_shadow_lock, flags);
	shadow_data = klp_shadow_get(obj, id);
	if (unlikely(shadow_data)) {

		/* Shadow variable found, throw away allocation and
		 * return the shadow variable data */
		spin_unlock_irqrestore(&klp_shadow_lock, flags);
		kfree(shadow_data);
		goto ret;
	}

	/* No <obj, id> found, so attach the newly allocated one */
	shadow_data = data;
	klp_shadow_set(new_shadow, obj, id, data, size);
	klp_shadow_add(new_shadow);
	spin_unlock_irqrestore(&klp_shadow_lock, flags);

ret:
	return shadow_data;
err:
	return NULL;
}
EXPORT_SYMBOL_GPL(klp_shadow_get_or_attach);

/**
 * klp_shadow_update_or_attach() - update or attach a new shadow variable
 * @obj:	pointer to parent object
 * @id:		data identifier
 * @data:	pointer to data to attach to parent
 * @size:	size of attached data
 * @gfp_flags:	GFP mask for allocation
 *
 * If an existing <obj, id> shadow variable can be found, it will be
 * updated and used in the return value of this function.
 *
 * Allocates @size bytes for new shadow variable data using @gfp_flags
 * and copies @size bytes from @data into the new shadow variable's own
 * data space.  If @data is NULL, @size bytes are still allocated, but
 * no copy is performed.  The new shadow variable is then added to the
 * global hashtable.
 *
 * Return: the shadow variable data element, NULL on failure.
 */
void *klp_shadow_update_or_attach(void *obj, unsigned long id, void *data,
				  size_t size, gfp_t gfp_flags)
{
	struct klp_shadow *new_shadow;
	void *shadow_data;
	unsigned long flags;

	/* Update/return a shadow variable if <obj, id> already exists */
	spin_lock_irqsave(&klp_shadow_lock, flags);
	shadow_data = klp_shadow_get(obj, id);
	if (shadow_data)
		goto update_unlock_ret;
	spin_unlock_irqrestore(&klp_shadow_lock, flags);

	/* Allocate a new shadow variable for use inside the lock below */
	new_shadow = kzalloc(size + sizeof(*new_shadow), gfp_flags);
	if (!new_shadow)
		goto err;

	/* Look for <obj, id> again under the lock, this time with an
	 * allocation in hand to use if need to use it. */
	spin_lock_irqsave(&klp_shadow_lock, flags);
	shadow_data = klp_shadow_get(obj, id);
	if (unlikely(shadow_data)) {

		/* Shadow variable found, throw away allocation and
		 * update/return the existing one */
		kfree(new_shadow);
		goto update_unlock_ret;
	}

	/* Could not find one, so attach the new one */
	shadow_data = data;
	klp_shadow_set(new_shadow, obj, id, data, size);
	klp_shadow_add(new_shadow);
	spin_unlock_irqrestore(&klp_shadow_lock, flags);

	return shadow_data;

update_unlock_ret:
	/* Update already attached shadow variable */
	new_shadow = container_of(shadow_data, struct klp_shadow, data);
	klp_shadow_set(new_shadow, obj, id, data, size);
	spin_unlock_irqrestore(&klp_shadow_lock, flags);

	return shadow_data;
err:
	return NULL;
}
EXPORT_SYMBOL_GPL(klp_shadow_update_or_attach);

/**
 * klp_shadow_detach() - detach and free a <obj, id> shadow variable
 * @obj:	pointer to parent object
 * @id:		data identifier
 */
void klp_shadow_detach(void *obj, unsigned long id)
{
	struct klp_shadow *shadow;
	unsigned long flags;

	spin_lock_irqsave(&klp_shadow_lock, flags);

	/* Delete <obj, id> from hash */
	hash_for_each_possible(klp_shadow_hash, shadow, node,
			       (unsigned long)obj) {

		if (shadow_match(shadow, obj, id)) {
			hash_del_rcu(&shadow->node);
			kfree_rcu(shadow, rcu_head);
			break;
		}
	}

	spin_unlock_irqrestore(&klp_shadow_lock, flags);
}
EXPORT_SYMBOL_GPL(klp_shadow_detach);

/**
 * klp_shadow_detach_all() - detach all <*, id> shadow variables
 * @id:		data identifier
 */
void klp_shadow_detach_all(unsigned long id)
{
	struct klp_shadow *shadow;
	unsigned long flags;
	int i;

	spin_lock_irqsave(&klp_shadow_lock, flags);

	/* Delete all <*, id> from hash */
	hash_for_each(klp_shadow_hash, i, shadow, node) {
		if (shadow_match(shadow, shadow->obj, id)) {
			hash_del_rcu(&shadow->node);
			kfree_rcu(shadow, rcu_head);
		}
	}

	spin_unlock_irqrestore(&klp_shadow_lock, flags);
}
EXPORT_SYMBOL_GPL(klp_shadow_detach_all);
