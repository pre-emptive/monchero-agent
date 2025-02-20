#!/bin/bash

WARNING_MIN=80
CRITICAL_MIN=90

echo "status: OK"
echo "check_name: Memory"
echo "metrics:"

if [ -n "${MONCHERO_AGENT_IS_DOCKERIZED}" ]; then
	if [ -n "${MONCHERO_AGENT_IS_CGROUP_V2}" ]; then
		FILE="/sys/fs/cgroup/memory.stat"
	else
		FILE="/sys/fs/cgroup/memory/memory.stat"
	fi
	while read LINE
	do
		IFS=' ' read -ra FIELDS <<< ${LINE}
		echo "  ${FIELDS[0]}:"
		echo "    value: ${FIELDS[1]}"

		declare MEM_${FIELDS[0]}=${FIELDS[1]}
	done < ${FILE}
	if [ -n "${MONCHERO_AGENT_IS_CGROUP_V2}" ]; then
		MEM_CURRENT=`cat /sys/fs/cgroup/memory.current`
		echo "  MemeoryCurrent:"
		echo "    value: ${MEM_CURRENT}"
		MEM_USED=`bc <<< "${MEM_CURRENT}-${MEM_inactive_file}"`
		MEM_MAX=`cat /sys/fs/cgroup/memory.max`
		if [ "${MEM_MAX}" != "max" ]; then
			# Unlimited memory, and we can't get the max physical
			# from inside the container :-(
			PC=""
		else
			PC=`bc <<< "${MEM_USED}/(${MEM_MAX}/100)"`
		fi
	else
		MEM_CURRENT=`cat /sys/fs/cgroup/memory/memory.usage_in_bytes`
		MAM_MAX=`cat /sys/fs/cgroup/memory/memory.limit_in_bytes`
		MEM_MAX=`bc <<< "${MEM_MAX}/1024"`
		MEM_USED=`bc <<< "${MEM_CURRENT}/1024"`
		PC=`bc <<< "${MEM_USED}/(${MEM_MAX}/100)"`
	fi
else

	while read LINE
	do
		IFS=' ' read -ra FIELDS <<< ${LINE}

		VAR=`echo "${FIELDS[0]}" | sed -e 's/://' -e 's/(/_/g' -e 's/)//g'`

		echo "  ${VAR}:"
		echo "    value: ${FIELDS[1]}"

		declare MEM_${VAR}=${FIELDS[1]}
	done < /proc/meminfo

	MEM_USED=`bc <<< "${MEM_MemTotal}-${MEM_MemAvailable}"`
	PC=`bc <<< "100-${MEM_MemAvailable}/(${MEM_MemTotal}/100)"`
fi

echo "  MemUsed:"
echo "    value: ${MEM_USED}"
if [ "${PC}" != "" ]; then
	echo "  MemUsed_pc:"
	echo "    value: ${PC}"
	echo "    warning_min: ${WARNING_MIN}"
	echo "    critical_min: ${CRITICAL_MIN}"

	echo "message: Used ${MEM_USED} (${PC}%) of ${MEM_MemTotal}, ${MEM_MemAvailable} available"
else
	echo "message: Used ${MEM_USED}, limit is unknown"
fi

