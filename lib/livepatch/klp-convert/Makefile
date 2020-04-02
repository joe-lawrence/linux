# SPDX-License-Identifier: GPL-2.0
#
# Makefile for livepatch klp-convert test code.

obj-$(CONFIG_TEST_LIVEPATCH) += \
	test_klp_convert1.o \
	test_klp_convert1__test_klp_convert_mod.o \
	test_klp_convert2.o \
	test_klp_convert2__test_klp_convert_mod.o \
	test_klp_convert_mod.o \
	test_klp_alt.o \
	test_klp_alt__test_klp_alt_mod.o \
	test_klp_alt_mod.o \
	test_klp_keys.o \
	test_klp_keys__test_klp_keys_mod.o \
	test_klp_keys_mod.o

test_klp_convert_mod-y := \
	test_klp_convert_mod_a.o \
	test_klp_convert_mod_b.o

# Target modules to be livepatched require CC_FLAGS_FTRACE
CFLAGS_test_klp_convert_mod.o		+= $(CC_FLAGS_FTRACE)
CFLAGS_test_klp_alt_mod.o 		+= $(CC_FLAGS_FTRACE)
CFLAGS_test_klp_static_keys_mod.o	+= $(CC_FLAGS_FTRACE)
CFLAGS_test_klp_keys_mod.o		+= $(CC_FLAGS_FTRACE)

# Set local include directory for modules that CREATE_TRACE_POINTS
CFLAGS_test_klp_keys_mod.o		+= -I$(src)
