#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2019 Joe Lawrence <joe.lawrence@redhat.com>

. $(dirname $0)/functions.sh

MOD_TARGET=test_klp_blacklist_mod
MOD_LIVEPATCH=test_klp_blacklist

set_dynamic_debug


# TEST: module srcversion blacklisting
#
# Test various combinations of module loading involving a target module
# and a livepatch that blacklists the target module's srcversion.
#
# - load a target module
# - load livepatch module which blacklists future loads of target module
# - unload the target module
# - try to load the target module (fails)
# - disable and unload the livepatch module
# - load the target module (succeeds)
# - unload the target module

echo -n "TEST: module srcversion blacklisting ... "
dmesg -C

load_mod $MOD_TARGET

SRCVER=$(modinfo $MOD_TARGET | awk '/^srcversion:/{print $NF}')
load_lp $MOD_LIVEPATCH srcversion=$SRCVER

unload_mod $MOD_TARGET
load_failing_mod $MOD_TARGET

disable_lp $MOD_LIVEPATCH
unload_lp $MOD_LIVEPATCH

load_mod $MOD_TARGET
unload_mod $MOD_TARGET

check_result "% modprobe $MOD_TARGET
$MOD_TARGET: ${MOD_TARGET}_init
% modprobe $MOD_LIVEPATCH srcversion=$SRCVER
livepatch: enabling patch '$MOD_LIVEPATCH'
livepatch: '$MOD_LIVEPATCH': initializing patching transition
livepatch: '$MOD_LIVEPATCH': starting patching transition
livepatch: '$MOD_LIVEPATCH': completing patching transition
livepatch: '$MOD_LIVEPATCH': patching complete
% rmmod $MOD_TARGET
$MOD_TARGET: ${MOD_TARGET}_exit
% modprobe $MOD_TARGET
livepatch: module: $MOD_TARGET, srcversion: $SRCVER has been blacklisted by livepatch $MOD_LIVEPATCH
modprobe: ERROR: could not insert '$MOD_TARGET': Invalid argument
% echo 0 > /sys/kernel/livepatch/$MOD_LIVEPATCH/enabled
livepatch: '$MOD_LIVEPATCH': initializing unpatching transition
livepatch: '$MOD_LIVEPATCH': starting unpatching transition
livepatch: '$MOD_LIVEPATCH': completing unpatching transition
livepatch: '$MOD_LIVEPATCH': unpatching complete
% rmmod $MOD_LIVEPATCH
% modprobe $MOD_TARGET
$MOD_TARGET: ${MOD_TARGET}_init
% rmmod $MOD_TARGET
$MOD_TARGET: ${MOD_TARGET}_exit"


exit 0
