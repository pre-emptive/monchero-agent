#!/bin/bash

# Part of Monchero Agent
# (C) 2025 Pre-Emptive Limited. GNU Public License v2 licensed.

WARNING_5_MIN_PER_CPU=5
CRITICAL_5_MIN_PER_CPU=10

NUM_CPUS="${MONCHERO_AGENT_NUMBER_OF_CPUS:-1}"

WARNING_THRESHOLD=$(( ${NUM_CPUS}*${WARNING_5_MIN_PER_CPU} ))
CRITICAL_THRESHOLD=$(( ${NUM_CPUS}*${CRITICAL_5_MIN_PER_CPU} ))

LOAD_AVG=`cat /proc/loadavg`
IFS=' ' read -ra FIELDS <<< ${LOAD_AVG}
IFS='/' read -ra VALS <<< ${FIELDS[3]}

echo "metrics:"
echo "  load_avg_1:"
echo "    value: ${FIELDS[0]}"
echo "  load_avg_5:"
echo "    value: ${FIELDS[1]}"
echo "    warning_min: ${WARNING_THRESHOLD}"
echo "    critcial_min: ${CRITICAL_THRESHOLD}"
echo "  load_avg_15:"
echo "    value: ${FIELDS[2]}"
echo "  threads:"
echo "    value: ${VALS[0]}"
echo "  kernel_entities:"
echo "    value: ${VALS[1]}"

# More metrics (available inside containers)
if [ -n "${MONCHERO_AGENT_IS_DOCKERIZED}" ]; then
    if [ -n "${MONCHERO_AGENT_IS_CGROUP_V2}" ]; then
        FILE="/sys/fs/cgroup/cpu.stat"
    else
        FILE="/sys/fs/cgroup/cpuacct/cpuacct.stat"
    fi
    sed -e 's/ /:\n    value: /g' -e 's/^/  /g' < ${FILE}
fi
