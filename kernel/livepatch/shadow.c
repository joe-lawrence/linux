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
 * <obj, key> pair and a pointer value.  It is the responsibility of the
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
 * struct klp_shadow - shadow variable structure
 * @node:	klp_shadow_hash hash table node
 * @rcu_head:	RCU is used to safely free this structure
 * @obj:	pointer to original data
 * @key:	key describing new data
 * @new_data:	pointer to new data
 */
struct klp_shadow {
	struct hlist_node node;
	struct rcu_head rcu_head;
	void *obj;
	unsigned long key;
	char new_data[];
};


static void klp_shadow_add(struct klp_shadow *shadow, void *obj)
{
	unsigned long flags;

	spin_lock_irqsave(&klp_shadow_lock, flags);
	hash_add_rcu(klp_shadow_hash, &shadow->node, (unsigned long)obj);
	spin_unlock_irqrestore(&klp_shadow_lock, flags);
}

/**
 * klp_shadow_attach - allocate and attach a new shadow variable
 * @obj:	pointer to original data
 * @key:	key describing new data
 * @new_data:	pointer to new data
 * @new_size:   size of new data
 * @gfp_mask:	GFP mask used to allocate shadow variable metadata
 *
 * Returns the shadow variable new_data element, NULL on failure.
 */
void *klp_shadow_attach(void *obj, unsigned long key, void *new_data,
			size_t new_size, gfp_t gfp_mask)
{
	struct klp_shadow *shadow;

	shadow = kzalloc(sizeof(*shadow) + new_size, gfp_mask);
	if (!shadow)
		return NULL;

	shadow->obj = obj;
	shadow->key = key;
	if (new_data)
		memcpy(shadow->new_data, new_data, new_size);

	klp_shadow_add(shadow, obj);

	return shadow->new_data;
}
EXPORT_SYMBOL_GPL(klp_shadow_attach);

static struct klp_shadow *klp_shadow_del(void *obj, unsigned long key)
{
	unsigned long flags;
	struct klp_shadow *shadow;

	spin_lock_irqsave(&klp_shadow_lock, flags);

	hash_for_each_possible(klp_shadow_hash, shadow, node,
			       (unsigned long)obj) {
		if (shadow->obj == obj && shadow->key == key) {
			hash_del_rcu(&shadow->node);
			return shadow;
		}
	}

	spin_unlock_irqrestore(&klp_shadow_lock, flags);
	return NULL;
}

/**
 * klp_shadow_detach - detach and free a shadow variable
 * @obj:	pointer to original data
 * @key:	key describing new data
 */
void klp_shadow_detach(void *obj, unsigned long key)
{
	struct klp_shadow *shadow;

	shadow = klp_shadow_del(obj, key);
	if (shadow)
		kfree_rcu(shadow, rcu_head);
}
EXPORT_SYMBOL_GPL(klp_shadow_detach);

/**
 * klp_shadow_get - retrieve a shadow variable new_data pointer
 * @obj:	pointer to original data
 * @key:	key describing new data
 */
void *klp_shadow_get(void *obj, unsigned long key)
{
	struct klp_shadow *shadow;

	rcu_read_lock();

	hash_for_each_possible_rcu(klp_shadow_hash, shadow, node,
				   (unsigned long)obj) {
		if (shadow->obj == obj && shadow->key == key) {
			rcu_read_unlock();
			return shadow->new_data;
		}
	}

	rcu_read_unlock();

	return NULL;
}
EXPORT_SYMBOL_GPL(klp_shadow_get);
