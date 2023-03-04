#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2018 Joe Lawrence <joe.lawrence@redhat.com>

. $(dirname $0)/functions.sh

MOD_LIVEPATCH=test_klp_livepatch
MOD_REPLACE=test_klp_atomic_replace
MOD_KLP_CONVERT_MOD=test_klp_convert_mod
MOD_KLP_CONVERT1=test_klp_convert1
MOD_KLP_CONVERT2=test_klp_convert2
MOD_KLP_CONVERT_DATA=test_klp_convert_data
MOD_KLP_CONVERT_SECTIONS=test_klp_convert_sections
MOD_KLP_CONVERT_KEYS_MOD=test_klp_convert_keys_mod
MOD_KLP_CONVERT_KEYS=test_klp_convert_keys

setup_config


# - load a livepatch that modifies the output from /proc/cmdline and
#   verify correct behavior
# - unload the livepatch and make sure the patch was removed

start_test "basic function patching"

load_lp $MOD_LIVEPATCH

if [[ "$(cat /proc/cmdline)" != "$MOD_LIVEPATCH: this has been live patched" ]] ; then
	echo -e "FAIL\n\n"
	die "livepatch kselftest(s) failed"
fi

disable_lp $MOD_LIVEPATCH
unload_lp $MOD_LIVEPATCH

if [[ "$(cat /proc/cmdline)" == "$MOD_LIVEPATCH: this has been live patched" ]] ; then
	echo -e "FAIL\n\n"
	die "livepatch kselftest(s) failed"
fi

check_result "% modprobe $MOD_LIVEPATCH
livepatch: enabling patch '$MOD_LIVEPATCH'
livepatch: '$MOD_LIVEPATCH': initializing patching transition
livepatch: '$MOD_LIVEPATCH': starting patching transition
livepatch: '$MOD_LIVEPATCH': completing patching transition
livepatch: '$MOD_LIVEPATCH': patching complete
% echo 0 > /sys/kernel/livepatch/$MOD_LIVEPATCH/enabled
livepatch: '$MOD_LIVEPATCH': initializing unpatching transition
livepatch: '$MOD_LIVEPATCH': starting unpatching transition
livepatch: '$MOD_LIVEPATCH': completing unpatching transition
livepatch: '$MOD_LIVEPATCH': unpatching complete
% rmmod $MOD_LIVEPATCH"


# - load a livepatch that modifies the output from /proc/cmdline and
#   verify correct behavior
# - load another livepatch and verify that both livepatches are active
# - unload the second livepatch and verify that the first is still active
# - unload the first livepatch and verify none are active

start_test "multiple livepatches"

load_lp $MOD_LIVEPATCH

grep 'live patched' /proc/cmdline > /dev/kmsg
grep 'live patched' /proc/meminfo > /dev/kmsg

load_lp $MOD_REPLACE replace=0

grep 'live patched' /proc/cmdline > /dev/kmsg
grep 'live patched' /proc/meminfo > /dev/kmsg

disable_lp $MOD_REPLACE
unload_lp $MOD_REPLACE

grep 'live patched' /proc/cmdline > /dev/kmsg
grep 'live patched' /proc/meminfo > /dev/kmsg

disable_lp $MOD_LIVEPATCH
unload_lp $MOD_LIVEPATCH

grep 'live patched' /proc/cmdline > /dev/kmsg
grep 'live patched' /proc/meminfo > /dev/kmsg

check_result "% modprobe $MOD_LIVEPATCH
livepatch: enabling patch '$MOD_LIVEPATCH'
livepatch: '$MOD_LIVEPATCH': initializing patching transition
livepatch: '$MOD_LIVEPATCH': starting patching transition
livepatch: '$MOD_LIVEPATCH': completing patching transition
livepatch: '$MOD_LIVEPATCH': patching complete
$MOD_LIVEPATCH: this has been live patched
% modprobe $MOD_REPLACE replace=0
livepatch: enabling patch '$MOD_REPLACE'
livepatch: '$MOD_REPLACE': initializing patching transition
livepatch: '$MOD_REPLACE': starting patching transition
livepatch: '$MOD_REPLACE': completing patching transition
livepatch: '$MOD_REPLACE': patching complete
$MOD_LIVEPATCH: this has been live patched
$MOD_REPLACE: this has been live patched
% echo 0 > /sys/kernel/livepatch/$MOD_REPLACE/enabled
livepatch: '$MOD_REPLACE': initializing unpatching transition
livepatch: '$MOD_REPLACE': starting unpatching transition
livepatch: '$MOD_REPLACE': completing unpatching transition
livepatch: '$MOD_REPLACE': unpatching complete
% rmmod $MOD_REPLACE
$MOD_LIVEPATCH: this has been live patched
% echo 0 > /sys/kernel/livepatch/$MOD_LIVEPATCH/enabled
livepatch: '$MOD_LIVEPATCH': initializing unpatching transition
livepatch: '$MOD_LIVEPATCH': starting unpatching transition
livepatch: '$MOD_LIVEPATCH': completing unpatching transition
livepatch: '$MOD_LIVEPATCH': unpatching complete
% rmmod $MOD_LIVEPATCH"


# - load a livepatch that modifies the output from /proc/cmdline and
#   verify correct behavior
# - load an atomic replace livepatch and verify that only the second is active
# - remove the first livepatch and verify that the atomic replace livepatch
#   is still active
# - remove the atomic replace livepatch and verify that none are active

start_test "atomic replace livepatch"

load_lp $MOD_LIVEPATCH

grep 'live patched' /proc/cmdline > /dev/kmsg
grep 'live patched' /proc/meminfo > /dev/kmsg

load_lp $MOD_REPLACE replace=1

grep 'live patched' /proc/cmdline > /dev/kmsg
grep 'live patched' /proc/meminfo > /dev/kmsg

unload_lp $MOD_LIVEPATCH

grep 'live patched' /proc/cmdline > /dev/kmsg
grep 'live patched' /proc/meminfo > /dev/kmsg

disable_lp $MOD_REPLACE
unload_lp $MOD_REPLACE

grep 'live patched' /proc/cmdline > /dev/kmsg
grep 'live patched' /proc/meminfo > /dev/kmsg

check_result "% modprobe $MOD_LIVEPATCH
livepatch: enabling patch '$MOD_LIVEPATCH'
livepatch: '$MOD_LIVEPATCH': initializing patching transition
livepatch: '$MOD_LIVEPATCH': starting patching transition
livepatch: '$MOD_LIVEPATCH': completing patching transition
livepatch: '$MOD_LIVEPATCH': patching complete
$MOD_LIVEPATCH: this has been live patched
% modprobe $MOD_REPLACE replace=1
livepatch: enabling patch '$MOD_REPLACE'
livepatch: '$MOD_REPLACE': initializing patching transition
livepatch: '$MOD_REPLACE': starting patching transition
livepatch: '$MOD_REPLACE': completing patching transition
livepatch: '$MOD_REPLACE': patching complete
$MOD_REPLACE: this has been live patched
% rmmod $MOD_LIVEPATCH
$MOD_REPLACE: this has been live patched
% echo 0 > /sys/kernel/livepatch/$MOD_REPLACE/enabled
livepatch: '$MOD_REPLACE': initializing unpatching transition
livepatch: '$MOD_REPLACE': starting unpatching transition
livepatch: '$MOD_REPLACE': completing unpatching transition
livepatch: '$MOD_REPLACE': unpatching complete
% rmmod $MOD_REPLACE"


# TEST: klp-convert symbols
# - load a livepatch that modifies the output from /proc/cmdline
#   including a reference to vmlinux-local symbol that klp-convert
#   will process
# - verify correct behavior
# - unload the livepatch and make sure the patch was removed

start_test "klp-convert symbols"

saved_cmdline=$(cat /proc/cmdline)

load_mod $MOD_KLP_CONVERT_MOD

load_lp $MOD_KLP_CONVERT1
echo 1 > /sys/module/$MOD_KLP_CONVERT1/parameters/print_debug
disable_lp $MOD_KLP_CONVERT1
unload_lp $MOD_KLP_CONVERT1

load_lp $MOD_KLP_CONVERT2
echo 1 > /sys/module/$MOD_KLP_CONVERT2/parameters/print_debug
disable_lp $MOD_KLP_CONVERT2
unload_lp $MOD_KLP_CONVERT2

unload_mod $MOD_KLP_CONVERT_MOD

check_result "% modprobe $MOD_KLP_CONVERT_MOD
% modprobe $MOD_KLP_CONVERT1
livepatch: enabling patch '$MOD_KLP_CONVERT1'
livepatch: '$MOD_KLP_CONVERT1': initializing patching transition
livepatch: '$MOD_KLP_CONVERT1': starting patching transition
livepatch: '$MOD_KLP_CONVERT1': completing patching transition
livepatch: '$MOD_KLP_CONVERT1': patching complete
$MOD_KLP_CONVERT1: saved_command_line, 0: $saved_cmdline
$MOD_KLP_CONVERT1: driver_name, 0: $MOD_KLP_CONVERT_MOD
$MOD_KLP_CONVERT1: test_klp_get_driver_name(), 0: $MOD_KLP_CONVERT_MOD
$MOD_KLP_CONVERT1: homonym_string, 1: homonym string A
$MOD_KLP_CONVERT1: get_homonym_string(), 1: homonym string A
test_klp_convert1: klp_string.12345 = lib/livepatch/test_klp_convert_mod_a.c static string
test_klp_convert1: klp_string.67890 = lib/livepatch/test_klp_convert_mod_b.c static string
% echo 0 > /sys/kernel/livepatch/$MOD_KLP_CONVERT1/enabled
livepatch: '$MOD_KLP_CONVERT1': initializing unpatching transition
livepatch: '$MOD_KLP_CONVERT1': starting unpatching transition
livepatch: '$MOD_KLP_CONVERT1': completing unpatching transition
livepatch: '$MOD_KLP_CONVERT1': unpatching complete
% rmmod $MOD_KLP_CONVERT1
% modprobe $MOD_KLP_CONVERT2
livepatch: enabling patch '$MOD_KLP_CONVERT2'
livepatch: '$MOD_KLP_CONVERT2': initializing patching transition
livepatch: '$MOD_KLP_CONVERT2': starting patching transition
livepatch: '$MOD_KLP_CONVERT2': completing patching transition
livepatch: '$MOD_KLP_CONVERT2': patching complete
$MOD_KLP_CONVERT2: saved_command_line (auto): $saved_cmdline
$MOD_KLP_CONVERT2: driver_name, 0: $MOD_KLP_CONVERT_MOD
$MOD_KLP_CONVERT2: test_klp_get_driver_name(), (auto): $MOD_KLP_CONVERT_MOD
$MOD_KLP_CONVERT2: homonym_string, 2: homonym string B
$MOD_KLP_CONVERT2: get_homonym_string(), 2: homonym string B
% echo 0 > /sys/kernel/livepatch/$MOD_KLP_CONVERT2/enabled
livepatch: '$MOD_KLP_CONVERT2': initializing unpatching transition
livepatch: '$MOD_KLP_CONVERT2': starting unpatching transition
livepatch: '$MOD_KLP_CONVERT2': completing unpatching transition
livepatch: '$MOD_KLP_CONVERT2': unpatching complete
% rmmod $MOD_KLP_CONVERT2
% rmmod $MOD_KLP_CONVERT_MOD"


# TEST: klp-convert symbols (late module patching)
# - load a livepatch that modifies the output from /proc/cmdline
#   including a reference to vmlinux-local symbol that klp-convert
#   will process
# - load target module
# - verify correct behavior
# - unload the livepatch

start_test "klp-convert symbols (late module patching)"

saved_cmdline=$(cat /proc/cmdline)

load_lp $MOD_KLP_CONVERT1
load_mod $MOD_KLP_CONVERT_MOD
echo 1 > /sys/module/$MOD_KLP_CONVERT1/parameters/print_debug
disable_lp $MOD_KLP_CONVERT1
unload_lp $MOD_KLP_CONVERT1
unload_mod $MOD_KLP_CONVERT_MOD

load_lp $MOD_KLP_CONVERT2
load_mod $MOD_KLP_CONVERT_MOD
echo 1 > /sys/module/$MOD_KLP_CONVERT2/parameters/print_debug
disable_lp $MOD_KLP_CONVERT2
unload_lp $MOD_KLP_CONVERT2
unload_mod $MOD_KLP_CONVERT_MOD

check_result "% modprobe $MOD_KLP_CONVERT1
livepatch: enabling patch '$MOD_KLP_CONVERT1'
livepatch: '$MOD_KLP_CONVERT1': initializing patching transition
livepatch: '$MOD_KLP_CONVERT1': starting patching transition
livepatch: '$MOD_KLP_CONVERT1': completing patching transition
livepatch: '$MOD_KLP_CONVERT1': patching complete
% modprobe $MOD_KLP_CONVERT_MOD
livepatch: applying patch '$MOD_KLP_CONVERT1' to loading module '$MOD_KLP_CONVERT_MOD'
$MOD_KLP_CONVERT1: saved_command_line, 0: $saved_cmdline
$MOD_KLP_CONVERT1: driver_name, 0: $MOD_KLP_CONVERT_MOD
$MOD_KLP_CONVERT1: test_klp_get_driver_name(), 0: $MOD_KLP_CONVERT_MOD
$MOD_KLP_CONVERT1: homonym_string, 1: homonym string A
$MOD_KLP_CONVERT1: get_homonym_string(), 1: homonym string A
test_klp_convert1: klp_string.12345 = lib/livepatch/test_klp_convert_mod_a.c static string
test_klp_convert1: klp_string.67890 = lib/livepatch/test_klp_convert_mod_b.c static string
% echo 0 > /sys/kernel/livepatch/$MOD_KLP_CONVERT1/enabled
livepatch: '$MOD_KLP_CONVERT1': initializing unpatching transition
livepatch: '$MOD_KLP_CONVERT1': starting unpatching transition
livepatch: '$MOD_KLP_CONVERT1': completing unpatching transition
livepatch: '$MOD_KLP_CONVERT1': unpatching complete
% rmmod $MOD_KLP_CONVERT1
% rmmod $MOD_KLP_CONVERT_MOD
% modprobe $MOD_KLP_CONVERT2
livepatch: enabling patch '$MOD_KLP_CONVERT2'
livepatch: '$MOD_KLP_CONVERT2': initializing patching transition
livepatch: '$MOD_KLP_CONVERT2': starting patching transition
livepatch: '$MOD_KLP_CONVERT2': completing patching transition
livepatch: '$MOD_KLP_CONVERT2': patching complete
% modprobe $MOD_KLP_CONVERT_MOD
livepatch: applying patch '$MOD_KLP_CONVERT2' to loading module '$MOD_KLP_CONVERT_MOD'
$MOD_KLP_CONVERT2: saved_command_line (auto): $saved_cmdline
$MOD_KLP_CONVERT2: driver_name, 0: $MOD_KLP_CONVERT_MOD
$MOD_KLP_CONVERT2: test_klp_get_driver_name(), (auto): $MOD_KLP_CONVERT_MOD
$MOD_KLP_CONVERT2: homonym_string, 2: homonym string B
$MOD_KLP_CONVERT2: get_homonym_string(), 2: homonym string B
% echo 0 > /sys/kernel/livepatch/$MOD_KLP_CONVERT2/enabled
livepatch: '$MOD_KLP_CONVERT2': initializing unpatching transition
livepatch: '$MOD_KLP_CONVERT2': starting unpatching transition
livepatch: '$MOD_KLP_CONVERT2': completing unpatching transition
livepatch: '$MOD_KLP_CONVERT2': unpatching complete
% rmmod $MOD_KLP_CONVERT2
% rmmod $MOD_KLP_CONVERT_MOD"


# TEST: klp-convert symbols across ELF sections
# - load a livepatch that references symbols that require klp-convert
#   and reference the same symbol from multiple ELF sections
# - verify correct behavior
# - unload the livepatch

start_test "klp-convert symbols across ELF sections"

saved_cmdline=$(cat /proc/cmdline)

load_mod $MOD_KLP_CONVERT_MOD
load_lp $MOD_KLP_CONVERT_SECTIONS
echo 1 > /sys/module/$MOD_KLP_CONVERT_SECTIONS/parameters/print_debug
disable_lp $MOD_KLP_CONVERT_SECTIONS
unload_lp $MOD_KLP_CONVERT_SECTIONS
unload_mod $MOD_KLP_CONVERT_MOD

check_result "% modprobe $MOD_KLP_CONVERT_MOD
% modprobe $MOD_KLP_CONVERT_SECTIONS
livepatch: enabling patch '$MOD_KLP_CONVERT_SECTIONS'
livepatch: '$MOD_KLP_CONVERT_SECTIONS': initializing patching transition
livepatch: '$MOD_KLP_CONVERT_SECTIONS': starting patching transition
livepatch: '$MOD_KLP_CONVERT_SECTIONS': completing patching transition
livepatch: '$MOD_KLP_CONVERT_SECTIONS': patching complete
$MOD_KLP_CONVERT_SECTIONS: saved_command_line (1): $saved_cmdline
$MOD_KLP_CONVERT_SECTIONS: saved_command_line (1): $saved_cmdline
$MOD_KLP_CONVERT_SECTIONS: saved_command_line (2): $saved_cmdline
$MOD_KLP_CONVERT_SECTIONS: saved_command_line (1): $saved_cmdline
$MOD_KLP_CONVERT_SECTIONS: saved_command_line (2): $saved_cmdline
$MOD_KLP_CONVERT_SECTIONS: saved_command_line (3): $saved_cmdline
$MOD_KLP_CONVERT_SECTIONS: test_klp_get_driver_name(): $MOD_KLP_CONVERT_MOD
$MOD_KLP_CONVERT_SECTIONS: p_test_klp_get_driver_name(): $MOD_KLP_CONVERT_MOD
$MOD_KLP_CONVERT_SECTIONS: get_homonym_string(): homonym string A
$MOD_KLP_CONVERT_SECTIONS: p_get_homonym_string(): homonym string A
% echo 0 > /sys/kernel/livepatch/$MOD_KLP_CONVERT_SECTIONS/enabled
livepatch: '$MOD_KLP_CONVERT_SECTIONS': initializing unpatching transition
livepatch: '$MOD_KLP_CONVERT_SECTIONS': starting unpatching transition
livepatch: '$MOD_KLP_CONVERT_SECTIONS': completing unpatching transition
livepatch: '$MOD_KLP_CONVERT_SECTIONS': unpatching complete
% rmmod $MOD_KLP_CONVERT_SECTIONS
% rmmod $MOD_KLP_CONVERT_MOD"


# TEST: klp-convert data relocations

start_test "klp-convert data relocations"

load_mod $MOD_KLP_CONVERT_MOD
load_lp $MOD_KLP_CONVERT_DATA

echo 1 > /sys/module/$MOD_KLP_CONVERT_DATA/parameters/print_debug

disable_lp $MOD_KLP_CONVERT_DATA
unload_lp $MOD_KLP_CONVERT_DATA
unload_mod $MOD_KLP_CONVERT_MOD

check_result "% modprobe $MOD_KLP_CONVERT_MOD
% modprobe $MOD_KLP_CONVERT_DATA
livepatch: enabling patch '$MOD_KLP_CONVERT_DATA'
livepatch: '$MOD_KLP_CONVERT_DATA': initializing patching transition
livepatch: '$MOD_KLP_CONVERT_DATA': starting patching transition
livepatch: '$MOD_KLP_CONVERT_DATA': completing patching transition
livepatch: '$MOD_KLP_CONVERT_DATA': patching complete
$MOD_KLP_CONVERT_DATA: local_small: 1111
$MOD_KLP_CONVERT_DATA: const_local_small: 2222
$MOD_KLP_CONVERT_DATA: static_local_small: 3333
$MOD_KLP_CONVERT_DATA: static_const_local_small: 4444
$MOD_KLP_CONVERT_DATA: local_large[0..3]: 1111 2222 3333 4444
$MOD_KLP_CONVERT_DATA: const_local_large[0..3]: 5555 6666 7777 8888
$MOD_KLP_CONVERT_DATA: static_local_large[0..3]: 9999 aaaa bbbb cccc
$MOD_KLP_CONVERT_DATA: static_const_local_large[0..3]: dddd eeee ffff 0
$MOD_KLP_CONVERT_DATA: global_small: 1111
$MOD_KLP_CONVERT_DATA: const_global_small: 2222
$MOD_KLP_CONVERT_DATA: static_small: 3333
$MOD_KLP_CONVERT_DATA: static_const_small: 4444
$MOD_KLP_CONVERT_DATA: global_large[0..3]: 1111 2222 3333 4444
$MOD_KLP_CONVERT_DATA: const_global_large[0..3]: 5555 6666 7777 8888
$MOD_KLP_CONVERT_DATA: static_large[0..3]: 9999 aaaa bbbb cccc
$MOD_KLP_CONVERT_DATA: static_const_large[0..3]: dddd eeee ffff 0
$MOD_KLP_CONVERT_DATA: static_read_mostly: 2222
% echo 0 > /sys/kernel/livepatch/$MOD_KLP_CONVERT_DATA/enabled
livepatch: '$MOD_KLP_CONVERT_DATA': initializing unpatching transition
livepatch: '$MOD_KLP_CONVERT_DATA': starting unpatching transition
livepatch: '$MOD_KLP_CONVERT_DATA': completing unpatching transition
livepatch: '$MOD_KLP_CONVERT_DATA': unpatching complete
% rmmod $MOD_KLP_CONVERT_DATA
% rmmod $MOD_KLP_CONVERT_MOD"


# TEST: klp-convert data relocations (late module patching)

start_test "klp-convert data relocations (late module patching)"

load_lp $MOD_KLP_CONVERT_DATA
load_mod $MOD_KLP_CONVERT_MOD

echo 1 > /sys/module/$MOD_KLP_CONVERT_DATA/parameters/print_debug

disable_lp $MOD_KLP_CONVERT_DATA
unload_lp $MOD_KLP_CONVERT_DATA
unload_mod $MOD_KLP_CONVERT_MOD

check_result "% modprobe $MOD_KLP_CONVERT_DATA
livepatch: enabling patch '$MOD_KLP_CONVERT_DATA'
livepatch: '$MOD_KLP_CONVERT_DATA': initializing patching transition
livepatch: '$MOD_KLP_CONVERT_DATA': starting patching transition
livepatch: '$MOD_KLP_CONVERT_DATA': completing patching transition
livepatch: '$MOD_KLP_CONVERT_DATA': patching complete
% modprobe $MOD_KLP_CONVERT_MOD
livepatch: applying patch '$MOD_KLP_CONVERT_DATA' to loading module '$MOD_KLP_CONVERT_MOD'
$MOD_KLP_CONVERT_DATA: local_small: 1111
$MOD_KLP_CONVERT_DATA: const_local_small: 2222
$MOD_KLP_CONVERT_DATA: static_local_small: 3333
$MOD_KLP_CONVERT_DATA: static_const_local_small: 4444
$MOD_KLP_CONVERT_DATA: local_large[0..3]: 1111 2222 3333 4444
$MOD_KLP_CONVERT_DATA: const_local_large[0..3]: 5555 6666 7777 8888
$MOD_KLP_CONVERT_DATA: static_local_large[0..3]: 9999 aaaa bbbb cccc
$MOD_KLP_CONVERT_DATA: static_const_local_large[0..3]: dddd eeee ffff 0
$MOD_KLP_CONVERT_DATA: global_small: 1111
$MOD_KLP_CONVERT_DATA: const_global_small: 2222
$MOD_KLP_CONVERT_DATA: static_small: 3333
$MOD_KLP_CONVERT_DATA: static_const_small: 4444
$MOD_KLP_CONVERT_DATA: global_large[0..3]: 1111 2222 3333 4444
$MOD_KLP_CONVERT_DATA: const_global_large[0..3]: 5555 6666 7777 8888
$MOD_KLP_CONVERT_DATA: static_large[0..3]: 9999 aaaa bbbb cccc
$MOD_KLP_CONVERT_DATA: static_const_large[0..3]: dddd eeee ffff 0
$MOD_KLP_CONVERT_DATA: static_read_mostly: 2222
% echo 0 > /sys/kernel/livepatch/$MOD_KLP_CONVERT_DATA/enabled
livepatch: '$MOD_KLP_CONVERT_DATA': initializing unpatching transition
livepatch: '$MOD_KLP_CONVERT_DATA': starting unpatching transition
livepatch: '$MOD_KLP_CONVERT_DATA': completing unpatching transition
livepatch: '$MOD_KLP_CONVERT_DATA': unpatching complete
% rmmod $MOD_KLP_CONVERT_DATA
% rmmod $MOD_KLP_CONVERT_MOD"


# TEST: klp-convert static keys
# - load a module which defines static keys, updates one of the keys on
#   load (forcing jump table patching)
# - load a livepatch that references the same keys, resolved by
#   klp-convert tool
# - poke the livepatch sysfs interface to update one of the key (forcing
#   jump table patching again)
# - disable and unload the livepatch
# - remove the module

start_test "klp-convert static keys"

load_mod $MOD_KLP_CONVERT_KEYS_MOD
load_lp $MOD_KLP_CONVERT_KEYS

echo 1 > /sys/module/$MOD_KLP_CONVERT_KEYS/parameters/enable_false_key

disable_lp $MOD_KLP_CONVERT_KEYS
unload_lp $MOD_KLP_CONVERT_KEYS
unload_mod $MOD_KLP_CONVERT_KEYS_MOD

check_result "% modprobe $MOD_KLP_CONVERT_KEYS_MOD
$MOD_KLP_CONVERT_KEYS_MOD: print_key_status: initial conditions
$MOD_KLP_CONVERT_KEYS_MOD: static_key_enabled(&test_klp_true_key) is true
$MOD_KLP_CONVERT_KEYS_MOD: static_key_enabled(&test_klp_false_key) is false
$MOD_KLP_CONVERT_KEYS_MOD: static_branch_likely(&test_klp_true_key) is true
$MOD_KLP_CONVERT_KEYS_MOD: static_branch_unlikely(&test_klp_false_key) is false
$MOD_KLP_CONVERT_KEYS_MOD: print_key_status: disabled test_klp_true_key
$MOD_KLP_CONVERT_KEYS_MOD: static_key_enabled(&test_klp_true_key) is false
$MOD_KLP_CONVERT_KEYS_MOD: static_key_enabled(&test_klp_false_key) is false
$MOD_KLP_CONVERT_KEYS_MOD: static_branch_likely(&test_klp_true_key) is false
$MOD_KLP_CONVERT_KEYS_MOD: static_branch_unlikely(&test_klp_false_key) is false
% modprobe $MOD_KLP_CONVERT_KEYS
livepatch: enabling patch '$MOD_KLP_CONVERT_KEYS'
livepatch: '$MOD_KLP_CONVERT_KEYS': initializing patching transition
livepatch: '$MOD_KLP_CONVERT_KEYS': starting patching transition
livepatch: '$MOD_KLP_CONVERT_KEYS': completing patching transition
livepatch: '$MOD_KLP_CONVERT_KEYS': patching complete
$MOD_KLP_CONVERT_KEYS: print_key_status: set_enable_false_key start
$MOD_KLP_CONVERT_KEYS: static_key_enabled(&tracepoint_printk_key) is false
$MOD_KLP_CONVERT_KEYS: static_key_enabled(&test_klp_true_key) is false
$MOD_KLP_CONVERT_KEYS: static_key_enabled(&test_klp_false_key) is false
$MOD_KLP_CONVERT_KEYS: static_branch_unlikely(&tracepoint_printk_key) is false
$MOD_KLP_CONVERT_KEYS: print_key_status: set_enable_false_key enabling test_klp_false_key
$MOD_KLP_CONVERT_KEYS: static_key_enabled(&tracepoint_printk_key) is false
$MOD_KLP_CONVERT_KEYS: static_key_enabled(&test_klp_true_key) is false
$MOD_KLP_CONVERT_KEYS: static_key_enabled(&test_klp_false_key) is true
$MOD_KLP_CONVERT_KEYS: static_branch_unlikely(&tracepoint_printk_key) is false
% echo 0 > /sys/kernel/livepatch/$MOD_KLP_CONVERT_KEYS/enabled
livepatch: '$MOD_KLP_CONVERT_KEYS': initializing unpatching transition
livepatch: '$MOD_KLP_CONVERT_KEYS': starting unpatching transition
livepatch: '$MOD_KLP_CONVERT_KEYS': completing unpatching transition
livepatch: '$MOD_KLP_CONVERT_KEYS': unpatching complete
% rmmod $MOD_KLP_CONVERT_KEYS
% rmmod $MOD_KLP_CONVERT_KEYS_MOD
$MOD_KLP_CONVERT_KEYS_MOD: print_key_status: unloading conditions
$MOD_KLP_CONVERT_KEYS_MOD: static_key_enabled(&test_klp_true_key) is false
$MOD_KLP_CONVERT_KEYS_MOD: static_key_enabled(&test_klp_false_key) is true
$MOD_KLP_CONVERT_KEYS_MOD: static_branch_likely(&test_klp_true_key) is false
$MOD_KLP_CONVERT_KEYS_MOD: static_branch_unlikely(&test_klp_false_key) is true"


# TEST: klp-convert static keys (late module patching)
# - load a module which defines static keys, updates one of the keys on
#   load (forcing jump table patching)
# - load a livepatch that references the same keys, resolved by
#   klp-convert tool
# - poke the livepatch sysfs interface to update one of the key (forcing
#   jump table patching again)
# - disable and unload the livepatch
# - remove the module

start_test "klp-convert static keys (late module patching)"

load_lp $MOD_KLP_CONVERT_KEYS
load_mod $MOD_KLP_CONVERT_KEYS_MOD

echo 1 > /sys/module/$MOD_KLP_CONVERT_KEYS/parameters/enable_false_key

disable_lp $MOD_KLP_CONVERT_KEYS
unload_lp $MOD_KLP_CONVERT_KEYS
unload_mod $MOD_KLP_CONVERT_KEYS_MOD

check_result "% modprobe $MOD_KLP_CONVERT_KEYS
livepatch: enabling patch '$MOD_KLP_CONVERT_KEYS'
livepatch: '$MOD_KLP_CONVERT_KEYS': initializing patching transition
livepatch: '$MOD_KLP_CONVERT_KEYS': starting patching transition
livepatch: '$MOD_KLP_CONVERT_KEYS': completing patching transition
livepatch: '$MOD_KLP_CONVERT_KEYS': patching complete
% modprobe $MOD_KLP_CONVERT_KEYS_MOD
livepatch: applying patch '$MOD_KLP_CONVERT_KEYS' to loading module '$MOD_KLP_CONVERT_KEYS_MOD'
$MOD_KLP_CONVERT_KEYS_MOD: print_key_status: initial conditions
$MOD_KLP_CONVERT_KEYS_MOD: static_key_enabled(&test_klp_true_key) is true
$MOD_KLP_CONVERT_KEYS_MOD: static_key_enabled(&test_klp_false_key) is false
$MOD_KLP_CONVERT_KEYS_MOD: static_branch_likely(&test_klp_true_key) is true
$MOD_KLP_CONVERT_KEYS_MOD: static_branch_unlikely(&test_klp_false_key) is false
$MOD_KLP_CONVERT_KEYS_MOD: print_key_status: disabled test_klp_true_key
$MOD_KLP_CONVERT_KEYS_MOD: static_key_enabled(&test_klp_true_key) is false
$MOD_KLP_CONVERT_KEYS_MOD: static_key_enabled(&test_klp_false_key) is false
$MOD_KLP_CONVERT_KEYS_MOD: static_branch_likely(&test_klp_true_key) is false
$MOD_KLP_CONVERT_KEYS_MOD: static_branch_unlikely(&test_klp_false_key) is false
$MOD_KLP_CONVERT_KEYS: print_key_status: set_enable_false_key start
$MOD_KLP_CONVERT_KEYS: static_key_enabled(&tracepoint_printk_key) is false
$MOD_KLP_CONVERT_KEYS: static_key_enabled(&test_klp_true_key) is false
$MOD_KLP_CONVERT_KEYS: static_key_enabled(&test_klp_false_key) is false
$MOD_KLP_CONVERT_KEYS: static_branch_unlikely(&tracepoint_printk_key) is false
$MOD_KLP_CONVERT_KEYS: print_key_status: set_enable_false_key enabling test_klp_false_key
$MOD_KLP_CONVERT_KEYS: static_key_enabled(&tracepoint_printk_key) is false
$MOD_KLP_CONVERT_KEYS: static_key_enabled(&test_klp_true_key) is false
$MOD_KLP_CONVERT_KEYS: static_key_enabled(&test_klp_false_key) is true
$MOD_KLP_CONVERT_KEYS: static_branch_unlikely(&tracepoint_printk_key) is false
% echo 0 > /sys/kernel/livepatch/$MOD_KLP_CONVERT_KEYS/enabled
livepatch: '$MOD_KLP_CONVERT_KEYS': initializing unpatching transition
livepatch: '$MOD_KLP_CONVERT_KEYS': starting unpatching transition
livepatch: '$MOD_KLP_CONVERT_KEYS': completing unpatching transition
livepatch: '$MOD_KLP_CONVERT_KEYS': unpatching complete
% rmmod $MOD_KLP_CONVERT_KEYS
% rmmod $MOD_KLP_CONVERT_KEYS_MOD
$MOD_KLP_CONVERT_KEYS_MOD: print_key_status: unloading conditions
$MOD_KLP_CONVERT_KEYS_MOD: static_key_enabled(&test_klp_true_key) is false
$MOD_KLP_CONVERT_KEYS_MOD: static_key_enabled(&test_klp_false_key) is true
$MOD_KLP_CONVERT_KEYS_MOD: static_branch_likely(&test_klp_true_key) is false
$MOD_KLP_CONVERT_KEYS_MOD: static_branch_unlikely(&test_klp_false_key) is true"


exit 0
