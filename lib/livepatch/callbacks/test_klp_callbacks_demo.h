// SPDX-License-Identifier: GPL-2.0
// Copyright (C) 2018 Joe Lawrence <joe.lawrence@redhat.com>

#include <linux/livepatch.h>

#define LIVEPATCH_NAME "test_klp_callbacks_demo"

int pre_patch_callback(struct klp_object *obj);
void post_patch_callback(struct klp_object *obj);
void pre_unpatch_callback(struct klp_object *obj);
void post_unpatch_callback(struct klp_object *obj);
