#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2018 Joe Lawrence <joe.lawrence@redhat.com>

# Shell functions for the rest of the scripts.

MAX_RETRIES=600
RETRY_INTERVAL=".1"	# seconds

# die(msg) - game over, man
#	msg - dying words
function die() {
	echo "ERROR: $1" >&2
	exit 1
}

# set_dynamic_debug() - setup kernel dynamic debug
#	TODO - push and pop this config?
function set_dynamic_debug() {
	cat << EOF > /sys/kernel/debug/dynamic_debug/control
file kernel/livepatch/* +p
func klp_try_switch_task -p
EOF
}

# wait_for_transition(modname)
#	modname - livepatch module name
wait_for_transition() {
	local mod="$1"; shift

	# Wait for livepatch transition  ...
	local i=0
	while [[ $(cat /sys/kernel/livepatch/"$mod"/transition) != "0" ]]; do
		i=$((i+1))
		if [[ $i -eq $MAX_RETRIES ]]; then
			die "failed to complete transition for module $mod"
		fi
		sleep $RETRY_INTERVAL
	done
}

# load_mod(modname, params) - load a kernel module
#	modname - module name to load
#       params  - module parameters to pass to modprobe
function load_mod() {
	local mod="$1"; shift
	local args="$*"

	local msg="% modprobe $mod $args"
	echo "${msg%% }" > /dev/kmsg
	ret=$(modprobe "$mod" "$args" 2>&1)
	if [[ "$ret" != "" ]]; then
		echo "$ret" > /dev/kmsg
		die "$ret"
	fi

	# Wait for module in sysfs ...
	local i=0
	while [ ! -e /sys/module/"$mod" ]; do
		i=$((i+1))
		if [[ $i -eq $MAX_RETRIES ]]; then
			die "failed to load module $mod"
		fi
		sleep $RETRY_INTERVAL
	done

	# Wait for livepatch ...
	if [[ $(modinfo "$mod" | awk '/^livepatch:/{print $NF}') == "Y" ]]; then

		# Wait for livepatch in sysfs ...
		local i=0
		while [ ! -e /sys/kernel/livepatch/"$mod" ]; do
			i=$((i+1))
			if [[ $i -eq $MAX_RETRIES ]]; then
				die "failed to load module $mod (sysfs)"
			fi
			sleep $RETRY_INTERVAL
		done
	fi
}

# load_failing_mod(modname, params) - load a kernel module, expect to fail
#	modname - module name to load
#       params  - module parameters to pass to modprobe
function load_failing_mod() {
	local mod="$1"; shift
	local args="$*"

	local msg="% modprobe $mod $args"
	echo "${msg%% }" > /dev/kmsg
	ret=$(modprobe "$mod" "$args" 2>&1)
	if [[ "$ret" == "" ]]; then
		echo "$mod unexpectedly loaded" > /dev/kmsg
		die "$mod unexpectedly loaded"
	fi
	echo "$ret" > /dev/kmsg
}

# unload_mod(modname) - unload a kernel module
#	modname - module name to unload
function unload_mod() {
	local mod="$1"

	# Wait for module reference count to clear ...
	local i=0
	while [[ $(cat /sys/module/"$mod"/refcnt) != "0" ]]; do
		i=$((i+1))
		if [[ $i -eq $MAX_RETRIES ]]; then
			die "failed to unload module $mod (refcnt)"
		fi
		sleep $RETRY_INTERVAL
	done

	echo "% rmmod $mod" > /dev/kmsg
	ret=$(rmmod "$mod" 2>&1)
	if [[ "$ret" != "" ]]; then
		echo "$ret" > /dev/kmsg
		die "$ret"
	fi

	# Wait for module in sysfs ...
	local i=0
	while [ -e /sys/module/"$mod" ]; do
		i=$((i+1))
		if [[ $i -eq $MAX_RETRIES ]]; then
			die "failed to unload module $mod (/sys/module)"
		fi
		sleep $RETRY_INTERVAL
	done

	# Wait for livepatch sysfs if applicable ...
	if [[ $(modinfo "$mod" | awk '/^livepatch:/{print $NF}') == "Y" ]]; then

		local i=0
		while [ -e /sys/kernel/livepatch/"$mod" ]; do
			i=$((i+1))
			if [[ $i -eq $MAX_RETRIES ]]; then
				die "failed to unload module $mod (/sys/livepatch)"
			fi
			sleep $RETRY_INTERVAL
		done
	fi
}

# display_lp(modname) - disable a livepatch
#	modname - module name to unload
function disable_lp() {
	local mod="$1"

        echo "% echo 0 > /sys/kernel/livepatch/$mod/enabled" > /dev/kmsg
        echo 0 > /sys/kernel/livepatch/"$mod"/enabled

	# Wait for livepatch enable to clear ...
	local i=0
	while [[ $(cat /sys/kernel/livepatch/"$mod"/enabled) != "0" ]]; do
		i=$((i+1))
		if [[ $i -eq $MAX_RETRIES ]]; then
			die "failed to disable livepatch $mod"
		fi
		sleep $RETRY_INTERVAL
	done
}

# set_pre_patch_ret(modname, pre_patch_ret)
#	modname - module name to set
#	pre_patch_ret - new pre_patch_ret value
function set_pre_patch_ret {
	local mod="$1"; shift
        local ret="$1"

        echo "% echo $1 > /sys/module/$mod/parameters/pre_patch_ret" > /dev/kmsg
        echo "$1" > /sys/module/"$mod"/parameters/pre_patch_ret

	local i=0
	while [[ $(cat /sys/module/"$mod"/parameters/pre_patch_ret) != "$1" ]]; do
		i=$((i+1))
		if [[ $i -eq $MAX_RETRIES ]]; then
			die "failed to set pre_patch_ret parameter for $mod module"
		fi
		sleep $RETRY_INTERVAL
	done
}

# filter_dmesg() - print a filtered dmesg
#	TODO - better filter, out of order msgs, etc?
function check_result {
	local expect="$*"
	local result=$(dmesg | grep -v 'tainting' | grep -e 'livepatch:' -e 'test_klp' | sed 's/^\[[ 0-9.]*\] //')

	if [[ "$expect" == "$result" ]] ; then
		echo "ok"
	else
		echo -e "not ok\n\n$(diff -upr --label expected --label result <(echo "$expect") <(echo "$result"))\n"
		die "livepatch kselftest(s) failed"
	fi
}
