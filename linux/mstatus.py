#!/usr/bin/env python3

# mstatus - show Monchero Agent local status

# Monchero Monitoring Platform
# (C) 2025 Pre-Emptive Limited. GNU Public License v2.

import os, sys
import json
from datetime import datetime, timezone

STATE_FILE = '/tmp/state'
CHECK_INTERVAL = 60
OUTPUT_CHECK_NAME_WIDTH = 40

ansi_colours = {
    "red": '\033[0;31m',
    "green": '\033[0;32m',
    "yellow": '\033[0;33m',
    "bold": '\033[1m',
    "nc": '\033[0m', # No Color/reset
}

def string_to_width(string, width):
    if len(string) > width:
        hack = int(width / 2)
        hack_l = hack - 1
        hack_r = 0 - (hack - 2)
        string = string[:hack_l] + '...' + string[hack_r:]

    return "{string:{width}s}".format(width=width, string=string)

if not sys.stdin or not sys.stdin.isatty():
    ansi_colours = {}

try:
    with open(STATE_FILE, 'r') as f:
        data = json.load(f)
except OSError as e:
    print("Could not open Monchero state file at {}: {}".format(STATE_FILE, str(e)))
    sys.exit(1)

timestamp = datetime.fromisoformat(data['timestamp'])
diff = datetime.now(timezone.utc).astimezone() - timestamp

diff_int = int(diff.total_seconds())
if diff_int > 2*CHECK_INTERVAL:
    print("{}Warning{} State may be stale, timestamp is {} seconds old".format(ansi_colours.get('yellow',''), ansi_colours.get('nc',''), diff_int))

print("State was written at {}".format(timestamp.strftime('%H:%M:%S %m/%d/%Y')))

states_to_colours = {
    'OK': 'green',
    'Warning': 'yellow',
    'Critical': 'red',
}

for check_name,info in data['checks'].items():
    state_colour = states_to_colours.get(info['status'])
    state_string = info['status']
    if state_string == 'OK':
        state_string = '   OK'
    print_format = "{} [{}{:8s}{}] {}"
    print(print_format.format(
        string_to_width(check_name, OUTPUT_CHECK_NAME_WIDTH),
        ansi_colours.get(state_colour, ''),
        state_string,
        ansi_colours.get('nc',''),
        info['message'],
    ))
