#!/bin/bash

# Part of Monchero Agent
# (C) 2025 Pre-Emptive Limited. GNU Public License v2 licensed.

echoerr() { echo "$@" 1>&2; }

RUNNING_SERVICES=0
EXITED_SERVICES=0

FAILED_SERVICES=0
ACTIVE_SERVICES=0
INACTIVE_SERVICES=0

LOADED_SERVICES=0
NOTFOUND_SERVICES=0
DEAD_SERVICES=0

systemctl --version > /dev/null 2>&1
if [ "$?" != "0" ]; then
    # Systemd not installed
    exit 1
fi

while read LINE
do
	IFS=' ' read -ra FIELDS <<< ${LINE}

	case "${FIELDS[1]}" in
		"loaded")
			let "LOADED_SERVICES=LOADED_SERVICES+1"
			case "${FIELDS[2]}" in
				"active")
					let "ACTIVE_SERVICES=ACTIVE_SERVICES+1"
					case "${FIELDS[3]}" in
						"running")
							let "RUNNING_SERVICES=RUNNING_SERVICES+1"
							;;
						"exited")
							let "EXITED_SERVICES=EXITED_SERVICES+1"
							;;
						"failed")
							let "FAILED_SERVICES=FAILED_SERVICES+1"
							;;
						*)
							echoerr "Unknown state[3] '${FIELDS[3]}' in systemctl line ${LINE}"
							;;
					esac
					;;
				"inactive")
					let "INACTIVE_SERVICES=INACTIVE_SERVICES+1"
					;;
				"failed")
					let "FAILED_SERVICES=FAILED_SERVICES+1"
					;;
				*)
					echoerr "Unknown state[2] '${FIELDS[2]}' in systemctl line ${LINE}"
					;;
			esac
			;;
		"not-found")
			let "NOTFOUND_SERVICES=NOTFOUND_SERVICES+1"
			;;
		"dead")
			let "DEAD_SERVICES=DEAD_SERVICES+1"
			;;
		*)
			echoerr "Unknown state[1] '${FIELDS[1]}' in systemctl line ${LINE}"
			;;
	esac

done <<< `systemctl list-units -t service --full --all --plain --no-legend`

echo "status: OK"
echo 'check_name: "Systemd Services"'
echo "message: \"${RUNNING_SERVICES} services running, ${LOADED_SERVICES} loaded, ${FAILED_SERVICES} failed, ${DEAD_SERVICES} dead\""
echo "metrics:"
echo "  running_services:"
echo "    value: ${RUNNING_SERVICES}"
echo "  exited_services:"
echo "    value: ${EXITED_SERVICES}"
echo "  failed_services:"
echo "    value: ${FAILED_SERVICES}"
echo "    warning_min: 1"
echo "  active_services:"
echo "    value: ${ACTIVE_SERVICES}"
echo "  inactive_services:"
echo "    value: ${INACTIVE_SERVICES}"
echo "  loaded_services:"
echo "    value: ${LOADED_SERVICES}"
echo "  notfound_services:"
echo "    value: ${NOTFOUND_SERVICES}"
echo "  dead_services:"
echo "    value: ${DEAD_SERVICES}"
echo "    warning_min: 1"
