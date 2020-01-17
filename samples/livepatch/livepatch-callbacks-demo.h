// SPDX-License-Identifier: GPL-2.0
// Copyright (C) 2018 Joe Lawrence <joe.lawrence@redhat.com>

#include <linux/livepatch.h>

#define LIVEPATCH_NAME "livepatch_callbacks_demo"

int sample_pre_patch_callback(struct klp_object *obj);
void sample_post_patch_callback(struct klp_object *obj);
void sample_pre_unpatch_callback(struct klp_object *obj);
void sample_post_unpatch_callback(struct klp_object *obj);
