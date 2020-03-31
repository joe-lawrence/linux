#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2018 Joe Lawrence <joe.lawrence@redhat.com>

. $(dirname $0)/functions.sh

MOD_KLP_CONVERT_MOD=test_klp_convert_mod
MOD_KLP_CONVERT1=test_klp_convert1
MOD_KLP_CONVERT2=test_klp_convert2
MOD_KLP_CONVERT1=test_klp_convert1
MOD_KLP_CONVERT1_SUBMOD=test_klp_convert1__test_klp_convert_mod
MOD_KLP_CONVERT2=test_klp_convert2
MOD_KLP_CONVERT2_SUBMOD=test_klp_convert2__test_klp_convert_mod
MOD_KLP_ALT_MOD=test_klp_alt_mod
MOD_KLP_ALT=test_klp_alt
MOD_KLP_ALT_SUBMOD=test_klp_alt__test_klp_alt_mod


setup_config


# TEST: klp-convert symbols
# - load a livepatch that modifies the output from /proc/cmdline
#   including a reference to vmlinux-local symbol that klp-convert
#   will process
# - verify correct behavior
# - unload the livepatch and make sure the patch was removed

echo -n "TEST: klp-convert symbols ... "
dmesg -C

saved_cmdline=$(cat /proc/cmdline)

load_mod $MOD_KLP_CONVERT_MOD

load_lp $MOD_KLP_CONVERT1
disable_lp $MOD_KLP_CONVERT1
unload_lp $MOD_KLP_CONVERT1

load_lp $MOD_KLP_CONVERT2
disable_lp $MOD_KLP_CONVERT2
unload_lp $MOD_KLP_CONVERT2

unload_mod $MOD_KLP_CONVERT_MOD

check_result "% modprobe $MOD_KLP_CONVERT_MOD
% modprobe $MOD_KLP_CONVERT1
$MOD_KLP_CONVERT1_SUBMOD: driver_name, 0: $MOD_KLP_CONVERT_MOD
$MOD_KLP_CONVERT1_SUBMOD: get_driver_name(), 0: $MOD_KLP_CONVERT_MOD
$MOD_KLP_CONVERT1_SUBMOD: homonym_string, 1: homonym string A
$MOD_KLP_CONVERT1_SUBMOD: get_homonym_string(), 1: homonym string A
livepatch: enabling patch '$MOD_KLP_CONVERT1'
livepatch: '$MOD_KLP_CONVERT1': initializing patching transition
livepatch: '$MOD_KLP_CONVERT1': starting patching transition
$MOD_KLP_CONVERT1: saved_command_line, 0: $saved_cmdline
livepatch: '$MOD_KLP_CONVERT1': completing patching transition
livepatch: '$MOD_KLP_CONVERT1': patching complete
% echo 0 > /sys/kernel/livepatch/$MOD_KLP_CONVERT1/enabled
livepatch: '$MOD_KLP_CONVERT1': initializing unpatching transition
livepatch: '$MOD_KLP_CONVERT1': starting unpatching transition
livepatch: '$MOD_KLP_CONVERT1': completing unpatching transition
livepatch: '$MOD_KLP_CONVERT1': unpatching complete
% rmmod $MOD_KLP_CONVERT1
% modprobe $MOD_KLP_CONVERT2
$MOD_KLP_CONVERT2_SUBMOD: driver_name, 0: $MOD_KLP_CONVERT_MOD
$MOD_KLP_CONVERT2_SUBMOD: get_driver_name(), (auto): $MOD_KLP_CONVERT_MOD
$MOD_KLP_CONVERT2_SUBMOD: homonym_string, 2: homonym string B
$MOD_KLP_CONVERT2_SUBMOD: get_homonym_string(), 2: homonym string B
livepatch: enabling patch '$MOD_KLP_CONVERT2'
livepatch: '$MOD_KLP_CONVERT2': initializing patching transition
livepatch: '$MOD_KLP_CONVERT2': starting patching transition
$MOD_KLP_CONVERT2: saved_command_line (auto): $saved_cmdline
livepatch: '$MOD_KLP_CONVERT2': completing patching transition
livepatch: '$MOD_KLP_CONVERT2': patching complete
% echo 0 > /sys/kernel/livepatch/$MOD_KLP_CONVERT2/enabled
livepatch: '$MOD_KLP_CONVERT2': initializing unpatching transition
livepatch: '$MOD_KLP_CONVERT2': starting unpatching transition
livepatch: '$MOD_KLP_CONVERT2': completing unpatching transition
livepatch: '$MOD_KLP_CONVERT2': unpatching complete
% rmmod $MOD_KLP_CONVERT2
% rmmod $MOD_KLP_CONVERT_MOD"

# TEST: klp-convert alternative instructions
echo -n "TEST: klp-convert alternative instructions ... "
dmesg -C

load_lp $MOD_KLP_ALT
load_mod $MOD_KLP_ALT_MOD
unload_mod $MOD_KLP_ALT_MOD
disable_lp $MOD_KLP_ALT
unload_lp $MOD_KLP_ALT

check_result "% modprobe $MOD_KLP_ALT
livepatch: enabling patch '$MOD_KLP_ALT'
livepatch: '$MOD_KLP_ALT': initializing patching transition
livepatch: '$MOD_KLP_ALT': starting patching transition
livepatch: '$MOD_KLP_ALT': completing patching transition
livepatch: '$MOD_KLP_ALT': patching complete
% modprobe $MOD_KLP_ALT_MOD
livepatch: applying patch '$MOD_KLP_ALT' to loading module '$MOD_KLP_ALT_MOD'
$MOD_KLP_ALT_SUBMOD: klp_function2
$MOD_KLP_ALT_SUBMOD: klp_function1
$MOD_KLP_ALT_MOD: mod_function2
$MOD_KLP_ALT_MOD: mod_function1
$MOD_KLP_ALT_MOD: mod_function1
$MOD_KLP_ALT_MOD: mod_function2
$MOD_KLP_ALT_SUBMOD: klp_function2
$MOD_KLP_ALT_SUBMOD: klp_function1
$MOD_KLP_ALT_MOD: mod_function2
$MOD_KLP_ALT_MOD: mod_function1
$MOD_KLP_ALT_MOD: mod_function1
$MOD_KLP_ALT_MOD: mod_function2
% rmmod $MOD_KLP_ALT_MOD
$MOD_KLP_ALT_SUBMOD: klp_function2
$MOD_KLP_ALT_SUBMOD: klp_function1
$MOD_KLP_ALT_MOD: mod_function2
$MOD_KLP_ALT_MOD: mod_function1
$MOD_KLP_ALT_MOD: mod_function1
$MOD_KLP_ALT_MOD: mod_function2
livepatch: reverting patch '$MOD_KLP_ALT' on unloading module '$MOD_KLP_ALT_MOD'
% echo 0 > /sys/kernel/livepatch/$MOD_KLP_ALT/enabled
livepatch: '$MOD_KLP_ALT': initializing unpatching transition
livepatch: '$MOD_KLP_ALT': starting unpatching transition
livepatch: '$MOD_KLP_ALT': completing unpatching transition
livepatch: '$MOD_KLP_ALT': unpatching complete
% rmmod $MOD_KLP_ALT"


exit 0
