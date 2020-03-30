# SPDX-License-Identifier: GPL-2.0
#
# Makefile for livepatch callback test code.

obj-$(CONFIG_TEST_LIVEPATCH) += \
	test_klp_callbacks_demo.o \
	test_klp_callbacks_demo__test_klp_callbacks_busy.o \
	test_klp_callbacks_demo__test_klp_callbacks_mod.o \
	test_klp_callbacks_demo2.o \
	test_klp_callbacks_busy.o \
	test_klp_callbacks_mod.o

# Target modules to be livepatched require CC_FLAGS_FTRACE
CFLAGS_test_klp_callbacks_busy.o	+= $(CC_FLAGS_FTRACE)
CFLAGS_test_klp_callbacks_mod.o		+= $(CC_FLAGS_FTRACE)
