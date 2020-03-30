# SPDX-License-Identifier: GPL-2.0
#
# Makefile for livepatch basic functionality test code.

obj-$(CONFIG_TEST_LIVEPATCH) += \
	test_klp_livepatch.o \
	test_klp_livepatch2.o \
	test_klp_livepatch2__test_klp_module.o \
	test_klp_busy_module.o \
	test_klp_module.o

# Target modules to be livepatched require CC_FLAGS_FTRACE
CFLAGS_test_klp_busy_module.o		+= $(CC_FLAGS_FTRACE)
CFLAGS_test_klp_module.o		+= $(CC_FLAGS_FTRACE)
