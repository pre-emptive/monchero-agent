#!/bin/bash
# Container detection

# Part of Monchero Agent
# (C) 2025 Pre-Emptive Limited. GNU Public License v2 licensed.

# This function more or less firectly lifted from CheckMK's agent
# https://github.com/Checkmk/checkmk/blob/5c22d0bd48b504232b8093630e8cb9813c9f1da2/agents/check_mk_agent.linux#L332
detect_container_environment() {
    if [ -f /.dockerenv ]; then
        MONCHERO_AGENT_IS_DOCKERIZED=1
    elif grep container=lxc /proc/1/environ >/dev/null 2>&1; then
        # Works in lxc environment e.g. on Ubuntu bionic, but does not
        # seem to work in proxmox (see CMK-1561)
        MONCHERO_AGENT_IS_LXC_CONTAINER=1
    elif grep 'lxcfs /proc/cpuinfo fuse.lxcfs' /proc/mounts >/dev/null 2>&1; then
        # Seems to work in proxmox
        MONCHERO_AGENT_IS_LXC_CONTAINER=1
    else
        unset MONCHERO_AGENT_IS_DOCKERIZED
        unset MONCHERO_AGENT_IS_LXC_CONTAINER
    fi

    if [ -n "${IS_DOCKERIZED}" ] || [ -n "${IS_LXC_CONTAINER}" ]; then
        if [ "$(stat -fc'%t' /sys/fs/cgroup)" = "63677270" ]; then
            MONCHERO_AGENT_IS_CGROUP_V2=1
            MONCHERO_AGENT_CGROUP_SECTION_SUFFIX="_cgroupv2"
        else
            unset MONCHERO_AGENT_IS_CGROUP_V2
            unset MONCHERO_AGENT_CGROUP_SECTION_SUFFIX
        fi
    fi
}

detect_container_environment

( set -o posix ; set ) | grep MONCHERO
