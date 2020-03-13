#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2018 Joe Lawrence <joe.lawrence@redhat.com>

. $(dirname $0)/functions.sh

MOD_LIVEPATCH=test_klp_livepatch
MOD_TARGET=test_klp_module
MOD_LIVEPATCH2=test_klp_livepatch2
MOD_LIVEPATCH2_MOD=test_klp_livepatch2__test_klp_module
MOD_REPLACE=test_klp_atomic_replace

setup_config


# TEST: basic function patching
# - load a livepatch that modifies the output from /proc/cmdline and
#   verify correct behavior
# - unload the livepatch and make sure the patch was removed

echo -n "TEST: basic function patching ... "
dmesg -C

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


# TEST: basic target module patching
# - load a target module that provides a simple sysfs status interface
# - load livepatch modules that patch the sysfs interface
# - unload the livepatch modules
# - verify original sysfs interface

echo -n "TEST: basic target module patching ... "
dmesg -C

load_mod $MOD_TARGET

load_lp $MOD_LIVEPATCH2

if [[ "$(cat /sys/module/${MOD_TARGET}/parameters/status)" != "$MOD_LIVEPATCH2_MOD: status: livepatched" ]] ; then
	echo -e "FAIL\n\n"
	die "livepatch kselftest(s) failed"
fi

disable_lp $MOD_LIVEPATCH2
unload_lp $MOD_LIVEPATCH2

if [[ "$(cat /sys/module/${MOD_TARGET}/parameters/status)" != "$MOD_TARGET: status: unpatched" ]] ; then
	echo -e "FAIL\n\n"
	die "livepatch kselftest(s) failed"
fi

unload_mod $MOD_TARGET

check_result "% modprobe $MOD_TARGET
$MOD_TARGET: ${MOD_TARGET}_init
% modprobe $MOD_LIVEPATCH2
livepatch: enabling patch '$MOD_LIVEPATCH2'
livepatch: '$MOD_LIVEPATCH2': initializing patching transition
livepatch: '$MOD_LIVEPATCH2': starting patching transition
livepatch: '$MOD_LIVEPATCH2': completing patching transition
livepatch: '$MOD_LIVEPATCH2': patching complete
% echo 0 > /sys/kernel/livepatch/${MOD_LIVEPATCH2}/enabled
livepatch: '$MOD_LIVEPATCH2': initializing unpatching transition
livepatch: '$MOD_LIVEPATCH2': starting unpatching transition
livepatch: '$MOD_LIVEPATCH2': completing unpatching transition
livepatch: '$MOD_LIVEPATCH2': unpatching complete
% rmmod $MOD_LIVEPATCH2
% rmmod $MOD_TARGET
$MOD_TARGET: ${MOD_TARGET}_exit"


# TEST: lone livepatch sub-module
# - try to load a livepatch sub-module without its parent module
echo -n "TEST: lone livepatch sub-module"
dmesg -C

load_failing_mod $MOD_LIVEPATCH2_MOD

check_result "% modprobe $MOD_LIVEPATCH2_MOD
livepatch: Can't load livepatch ($MOD_LIVEPATCH2_MOD) for module when the livepatch ($MOD_LIVEPATCH2) for vmcore is not loaded
livepatch: patch '???' failed for module 'test_klp_module', refusing to load module 'test_klp_module'
modprobe: ERROR: could not insert '$MOD_LIVEPATCH2_MOD': Invalid argument"


# TEST: multiple livepatches
# - load a livepatch that modifies the output from /proc/cmdline and
#   verify correct behavior
# - load another livepatch and verify that both livepatches are active
# - unload the second livepatch and verify that the first is still active
# - unload the first livepatch and verify none are active

echo -n "TEST: multiple livepatches ... "
dmesg -C

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


# TEST: atomic replace livepatch
# - load a livepatch that modifies the output from /proc/cmdline and
#   verify correct behavior
# - load an atomic replace livepatch and verify that only the second is active
# - remove the first livepatch and verify that the atomic replace livepatch
#   is still active
# - remove the atomic replace livepatch and verify that none are active

echo -n "TEST: atomic replace livepatch ... "
dmesg -C

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


exit 0
