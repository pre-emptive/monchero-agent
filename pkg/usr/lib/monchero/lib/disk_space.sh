#!/bin/bash

WARNING_MIN=80
CRITICAL_MIN=90

# This lifted from CheckMK: https://github.com/Checkmk/checkmk/blob/5c22d0bd48b504232b8093630e8cb9813c9f1da2/agents/check_mk_agent.linux#L686
if [ -n "${MONCHERO_AGENT_IS_DOCKERIZED}" ]; then
    return
fi

# The exclusion list is getting a bit of a problem.
# -l should hide any remote FS but seems to be all but working.
excludefs="-x smbfs -x cifs -x iso9660 -x udf -x nfsv4 -x nfs -x mvfs -x prl_fs -x squashfs -x devtmpfs -x autofs -x beegfs"
if [ -z "${MONCHERO_AGENT_IS_LXC_CONTAINER}" ]; then
    excludefs="${excludefs} -x zfs"
fi

while read LINE
do
	# Line is something like:
	# /dev/vda1      ext4     20529812 3198836  16266164      17% /
	# headings:
	# Filesystem     Type  1024-blocks    Used Available Capacity Mounted on

	IFS=' ' read -ra FIELDS <<< ${LINE}

	CAPACITY=${FIELDS[5]%\%}

    HUMAN=`df -h ${FIELDS[6]} | tail -n +2`
    IFS=' ' read -ra MSG <<< ${HUMAN}

	echo "- status: OK"
	echo "  message: ${MSG[2]} of ${MSG[1]} (${CAPACITY}%) used, ${MSG[3]} available"
	echo "  check_name: \"Diskspace ${FIELDS[6]}\""
	echo "  metrics:"
	echo "    blocks:"
	echo "      value: ${FIELDS[2]}"
	echo "    blocks_used:"
	echo "      value: ${FIELDS[3]}"
	echo "    block_available:"
	echo "      value: ${FIELDS[4]}"
	echo "    blocks_capacity:"
	echo "      value: ${CAPACITY}"
	echo "      warning_min: ${WARNING_MIN}"
	echo "      critical_min: ${CRITICAL_MIN}"

    INODES=`df -PTli ${FIELDS[6]} | tail -n +2`
    IFS=' ' read -ra FIELDS <<< ${INODES}
    CAPACITY=`echo ${FIELDS[5]} | sed 's/%//'`

    echo "    inodes:"
	echo "      value: ${FIELDS[2]}"
	echo "    inodes_used:"
	echo "      value: ${FIELDS[3]}"
	echo "    inodes_available:"
	echo "      value: ${FIELDS[4]}"
	echo "    inodes_capacity:"
	echo "      value: ${CAPACITY}"
	echo "      warning_min: ${WARNING_MIN}"
	echo "      critical_min: ${CRITICAL_MIN}"

done <<< `df -PTlk ${excludefs} | tail -n +2`
