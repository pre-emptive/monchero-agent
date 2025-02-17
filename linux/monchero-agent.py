#!/usr/bin/env python3

# monchero-agent.py - Monchero Agent

# Monchero Monitoring Platform
# (C) 2025 Pre-Emptive Limited. GNU Public License v2.

import sys, os, os.path
import json, yaml
import subprocess
import threading
from datetime import datetime, timezone, timedelta
import pytz
import time
import configargparse
import logging
import re
import random
import socket
import requests

VERSION="0.0.1"

executable_database = []
check_database = {}
check_config = {
    'check_config': {},
    'plugin_config': {},
    'script_config': {},
    'command_config': {},
    'nagios_config': {},
}
config_args = None
logger = None
our_hostname = None

def to_number(something):
    if type(something) == int or type(something) == float:
        return something
    if type(something) == str:
        if '.' in something:
            try:
                return float(something)
            except ValueError:
                raise ValueError("Could not convert '{}' to float".format(something))
        try:
            return int(something)
        except ValueError:
            raise ValueError("Could not convert '{}' to int".format(something))
    raise ValueError("Could not convert '{}' (type {}) to a number".format(something, str(type(something))))

def insert_executable_into_database(executable):
    global executable_database
    # Special case?
    if len(executable_database) == 0:
        executable_database.append(executable)
        return

    try:
        previous_next_check_time = executable_database[0]['next_check']
    except IndexError:
        previous_next_check_time = datetime.min.replace(tzinfo=pytz.UTC)

    for i in range(len(executable_database)):
        if executable['next_check'] < previous_next_check_time:
            # insert just previous to this item
            logger.debug("Inserting check at index {}".format(i))
            executable_database.insert(i, executable)
            return
        previous_next_check_time = executable_database[i]['next_check']

    # Got to the end of the list, just append it
    executable_database.append(executable)

def pop_and_reinsert_executable(index=0):
    global executable_database
    executable = executable_database.pop(index)
    # Add some jitter to the next check time
    next_check = datetime.now(timezone.utc) + timedelta(seconds = executable['interval']) + timedelta(seconds = random.random())
    executable['next_check'] = next_check
    insert_executable_into_database(executable)

def initialise_executables(executable_dir, executable_type='native', interval=None, subdir=False):
    if not os.path.isdir(executable_dir):
        logger.debug('{} executable directory {} does not exist'.format(executable_type, executable_dir))
        return

    if interval is None:
        interval = config_args.interval

    # Start with ordinary executables
    executables = [
        f for f in os.listdir(executable_dir) if os.path.isfile(os.path.join(executable_dir, f)) and os.access(os.path.join(executable_dir, f),os.X_OK)
    ]

    for executable in executables:
        # Skip hidden files and common backup suffixes
        if executable.startswith('.') or executable.endswith('.bak') or  executable.endswith('.rpmsave') or executable.endswith('.old') or executable.endswith('.orig'):
            continue
        filename = os.path.join(executable_dir, executable)
        # DON'T add some jitter this time. This makes us run all the checks initially at full speed
        # so we populate our state immediately, and then spread out checks after that
        insert_executable_into_database({
            'filename': filename,
            'arguments': [],
            'interval': interval,
            'timestamp': datetime.now(timezone.utc),
            'next_check': datetime.now(timezone.utc),
            'executable_type': executable_type,
        })

    # We need to look in subdirectories, but recursion is unnecessary
    if not subdir:
        # Now do any timed checks (checks in numerically named subdirectories)
        timed_directories = [
            f for f in os.listdir(executable_dir) if str(f).isdigit() and os.path.isdir(os.path.join(executable_dir, f))
        ]
        for timed_dir in timed_directories:
            dir_path = os.path.join(executable_dir, timed_dir)
            initialise_executables(dir_path, executable_type, int(timed_dir), True)

def initialise_commands():
    global check_config
    # Rather than looking in the filesystem for things to do, we use the check_config instead
    for thing in ['command', 'nagios']:
        key = '{}_config'.format(thing)
        for command, config in check_config[key].items():
            logger.debug('found {} {} with config {}'.format(thing, command, config))
            if os.access(command, os.X_OK):
                # is executable, so usable
                # Add a little jitter to the next check time to spread executions out
                next_check = datetime.now(timezone.utc) + timedelta(seconds = random.random())
                check_name = config.get('check_name', os.path.basename(command))
                insert_executable_into_database({
                    'filename': command,
                    'arguments': config.get('arguments', []),
                    'interval': config.get('interval', config_args.interval),
                    'timestamp': datetime.now(timezone.utc),
                    'next_check': next_check,
                    'executable_type': thing,
                })

# state_wash() take a state (eg. 'OK') and washes it to make sure it's one of our preferred
# strings
def state_wash(state):
    acceptable_states = {
        'OK': ['ok', 'okay', "0", 0],
        'Warning': ['warning', "1", 1],
        'Critical': ['critical', "2", 2],
        'Unknown': ['unknown', "3", 3],
    }
    if state in acceptable_states.keys():
        # no wash needed
        return state

    # Bear in mind state may not be a string
    try:
        state = state.strip(' ')
        state = state.lower()
    except AttributeError:
        pass

    for key,values in acceptable_states.items():
        if state in values:
            return key
    # Couldn't wash
    return None

def parse_native_output(output, executable):
    # Parse, be as forgiving as possible
    try:
        parsed = yaml.load(output, Loader=yaml.SafeLoader)
    except yaml.YAMLError as e:
        logger.error("Could not parse output from check {}: {}".format(executable['filename'], str(e)))
        return None

    # Checks can be single or multiple
    if type(parsed) is list:
        usable = {}
        for item in parsed:
            if type(item) != dict:
                logger.warning("Output from {} was not a dict type - skipping it".format(executable['filename']))
                continue
            # status must be present, or else we can't use it
            if 'status' in item:
                usable[item['check_name']] = item
                item.pop('check_name')
            else:
                logger.warning("Output from {} does not contain a 'status' key - skipping it".format(executable['filename']))
                logger.debug('Output from {} is {}'.format(executable['filename'], item))
                continue
        parsed = usable
    elif type(parsed) != dict:
        logger.warning("Output from {} was not a dict type - skipping it".format(executable['filename']))
        return None
    else:
        if 'status' not in parsed:
            logger.warning("Output from {} does not contain a 'status' key - skipping it".format(executable['filename']))
            logger.debug('Output from {} is {}'.format(executable['filename'], parsed))
            return None

        check_name = parsed['check_name']
        parsed.pop('check_name')
        parsed = {
            check_name: parsed
        }

    # Wash the metrics. This should be copying good stuff from new into output
    for check, info in parsed.items():
        try:
            for metric, details in info['metrics'].items():
                for key in ['value','warning_min','warning_max','critical_min','critical_max']:
                    try:
                        details[key] = to_number(details[key])
                    except ValueError:
                        logging.debug('Metric {} {} in executable {} not a number'.format(key, details['value'], executable['filename']))
        except KeyError:
            continue

    return parsed

def parse_checkmk_output(output, executable):
    # Something like:
    # 0 bacula_backups - OK because This host does not particpate in regular backups\nExtended messages
    # 0 memcache connect_ms=5.274295806884766|set_get_delete_ms=7.222652435302734 Connected in 5.27 mS, set/get/delete in 7.22 mS
    # 0 "nginx threads" ActiveConn=1|reading=0|writing=1|waiting=0 OK - ActiveConn:1 reading:0 writing:1 waiting:0
    # 0 check_redis connect_ms=0.0019|set_ms=0.3202|read_ms=0.3283|delete_ms=0.5817 Connect: 0.00ms, set: 0.32ms, read: 0.33ms, delete: 0.58ms

    parsed = {}

    for line in output.split("\n"):
        if line == '':
            continue

        extended_message = None
        parts = re.findall(r'[^"\s]\S*|".+?"', line)
        try:
            status,check_name,metrics_string,message = [parts[0], parts[1], parts[2], ' '.join(parts[3:])]
        except IndexError:
            logger.debug("Skipping malformed line '{}' from {}".format(line, executable['filename']))
            continue

        try:
            status = int(status)
        except ValueError:
            logger.debug("Non-integer status in line '{}' from {}".format(line, executable['filename']))
            continue

        check_name = check_name.strip('"')

        metrics = {}
        if metrics_string != '-':
            for item in metrics_string.split('|'):
                try:
                    key,value = item.split('=')
                except ValueError:
                    logger.debug("Could not parse metric {} from {}".format(line, executable['filename']))
                    continue
                try:
                    details = parse_nagios_metric(value)
                except ValueError as e:
                    logger.debug("Could not parse metric {} from {}: {}".format(item, executable['filename'], str(e)))
                    continue
                metrics[key] = details

        # CheckMK can have extra message information, separated from the main message by the characters \ and n (\n) - not an actual
        # carriage return!
        if '\\n' in message:
            message, extended_message = message.split('\\n')

        parsed[check_name] = {
            'status': status,
            'message': message,
            'metrics': metrics,
        }
        if extended_message:
            parsed[check_name]['extended_message'] = extended_message

    return parsed

# Work out a status from a return code and some config details. The okays, warnings and criticals
# should be lists of numbers, or else an empty list.
def work_out_exit_code_status(exitcode, okays, warnings, criticals):
    if exitcode in okays:
        return 'OK'
    elif exitcode in warnings:
        return 'Warning'
    elif exitcode in criticals:
        return 'Critical'

    # Now we're guessing at the best thing to do. If it's a 0, then it's probably OK
    if exitcode == 0:
        return 'OK'

    # If anything else was configured, and it's not one of those, then we can say it's unknown
    if warnings or criticals:
        return 'Unknown'

    # Otherwise, it's non-zero, so we'll say it's bad
    return 'Critical'

# parses a nagios format range (also used by CheckMK). See https://nagios-plugins.org/doc/guidelines.html#THRESHOLDFORMAT
def parse_nagios_range(thing):
    mode = 'outside'
    minimum = None
    maximum = None

    if thing.startswith('@'):
        mode = 'inside'
        thing = thing.lstrip('@')

    if ':' in thing:
        minimum,maximum = thing.split(':', 1)
        if minimum == '~':
            minimum = None
        elif minimum == '':
            minimum = 0
        else:
            try:
                minimum = to_number(minimum)
            except ValueError:
                raise ValueError('Minimum is not a number: {}'.format(minimum))
        if maximum == '':
            maximum = None
        else:
            try:
                maximum = to_number(maximum)
            except ValueError:
                raise ValueError('Maximum is not a number: {}'.format(maximum))
    else:
        # no colon in it, so it's just a minimum
        try:
            minimum = to_number(thing)
        except ValueError:
            raise ValueError('Range minimum is not a number: {}'.format(thing))

    if maximum and minimum and maximum <= minimum:
        raise ValueError('Minimum not less than maximum')

    return (minimum, maximum, mode)

# Parse a Nagios/CheckMK metric string into consituent parts
# starts with something that looks like:
# 123;80:90;90
# returns a dict which looks like:
# {'value': 123, 'warning_min': 80, 'warning_max': 90, 'critical_min': 90, 'critical_max': '~', 'critical_mode': 'outside'}
# the warning* and critical* keys only get set if they're specified in the Nagios metric
def parse_nagios_metric(metric):
    # a metric looks something like 0.025030s;;;0.000000

    output = {
        'value': None,
    }

    try:
        value, therest = metric.split(';', 1)
    except ValueError:
        value = metric
        therest = ''

    # See if there's a Unit of Measurement (UOM)
    try:
        m = re.match(r'^([\d.]*)(\D*)$', value)
        if not m:
            logger.debug('match is none: {}'.format(value))
            return
        value = m.group(1)
        uom = m.group(2)
    except IndexError:
        raise ValueError('value/UOM')

    # Ensure value is numeric
    try:
        value = to_number(value)
    except ValueError:
        raise ValueError('value type')

    output['value'] = value

    # Now try to figure out warn/crit/min/max
    # we don't support min/max, so we skip those
    parts = therest.split(';')
    for key in ['warning','critical']:
        try:
            item = parts.pop(0)
        except IndexError:
            break
        if item == '':
            continue
        try:
            output['{}_min'.format(key)], output['{}_max'.format(key)], output['{}_mode'.format(key)] = parse_nagios_range(item)
        except ValueError:
            logger.debug('Metric {} has invalid {} range: {}'.format(metric, key, item))
            continue

    return output

def parse_nagios_output_string(line):
    # something like:
    # HTTP OK: HTTP/1.1 200 OK - 659 bytes in 0.025 second response time |time=0.025030s;;;0.000000 size=659B;;;0
    # see: https://nagios-plugins.org/doc/guidelines.html#AEN200

    try:
        message, metrics_string = line.split('|', 1)
    except ValueError:
        return (line, {})

    message = message.rstrip(' ')

    metrics = {}

    # Metrics are of this format: 'label'=value[UOM];[warn];[crit];[min];[max]
    # (separated by a space - beware the label can have spaces if it's quoted)
    if metrics_string != '':
        # This RE is a bit crusty and returns some '' and ' ' entries
        # otherwise, it splits on spaces but honours single quoted labels
        parts = re.split("( +|'[^']+'=[^ ]+)", metrics_string)
        for metric in parts:
            if metric == '' or metric == ' ':
                # Skip this 'noise' in the signal
                continue
            try:
                label, therest = metric.split('=')
            except ValueError:
                logger.debug('Nagios metric {} was not parseable (format)'.format(metric))
                continue
            label.strip("'")

            details = parse_nagios_metric(therest)

            # We don't (yet) support doing anything with the Unit of Measurement (UOM). We
            # could be normalising (say) KB/MB/GB into bytes, or mS, uS into Seconds, etc.

            metrics[label] = details

    return (message, metrics)


def parse_generic_output(output, exitcode, executable):
    config_key = '{}_config'.format(executable['executable_type'])

    try:
        item_config = check_config[config_key][executable['filename']]
    except KeyError:
        item_config = {}

    logger.debug("Generic output parsing {} type with config {}".format(executable['executable_type'], item_config))

    # Default to nagios type exit codes, then take on whatever config if we're not a nagios executable
    okay_exit_codes = [0]
    warning_exit_codes = [1]
    critical_exit_codes = [2]
    if executable['executable_type'] != 'nagios':
        okay_exit_codes = item_config.get('okay_exit_codes', [])
        warning_exit_codes = item_config.get('warning_exit_codes', [])
        critical_exit_codes = item_config.get('critical_exit_codes', [])

    status = work_out_exit_code_status(exitcode, okay_exit_codes, warning_exit_codes, critical_exit_codes)

    lines = output.split("\n")
    metrics = {}
    try:
        message = lines[0]
    except KeyError:
        message = ''

    # See if we can parse out some/all of the message
    if executable['executable_type'] == 'nagios':
        message, metrics = parse_nagios_output_string(message)

    if message == '':
        message = '(no output)'

    try:
        if lines[-1] == '':
            del lines[-1]
    except KeyError:
        pass
    # If lines is empty, or if lines is just one element, don't use it
    extended_message = None
    if len(lines) > 1:
        extended_message = "\n".join(lines)

    check_name = item_config.get('check_name', os.path.basename(executable['filename']))
    record = {
        'status': status,
        'message': message,
        'metrics': metrics,
    }
    if extended_message:
        record['extended_message'] = extended_message
    return {
        check_name: record,
    }

def run_executable(executable):
    result = subprocess.run(executable['filename'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if result.stderr:
        logger.warning("Executable {} emitted some STDERR: {}".format(executable['filename'], result.stderr))

    stdout = result.stdout.decode('utf-8')

    parsed = {}
    if executable['executable_type'] == 'checkmk':
        parsed = parse_checkmk_output(stdout, executable)
    elif executable['executable_type'] in ['script', 'command', 'nagios']:
        parsed = parse_generic_output(stdout, result.returncode, executable)
    else:
        parsed = parse_native_output(stdout, executable)

    if not parsed:
        # Got nothing back from the parser. Should have already been logged
        return

    new_status = {}
    for check_name,status in parsed.items():
        #check_name = os.path.basename(executable['filename'])
        record = {
            'status': 'Unknown',
            'message': '',
            'metrics': {},
        }
        try:
            record['status'] = state_wash(status['status'])
        except KeyError:
            record['status'] = 'Unknown'
            record['message'] = 'Check did not provide a status'

        for key in ['message', 'metrics', 'extended_message']:
            if key in status:
                record[key] = status[key]

        # Also change the whole check's record of interval if it's included in any
        # individual statuses
        try:
            # This does undefined things if there are multiple different intervals on a
            # single script
            executable['interval'] = status['interval']
        except KeyError:
            # Leave it as it is
            pass
        new_status[check_name] = record

    return new_status

def check_metric_in_range(metric):
    statuses = {
        'critical': 'Critical',
        'warning': 'Warning',
    }

    # Don't mess with the original
    metric = metric.copy()

    # Try the "worst" first, then the "least worst"
    for level in ['critical', 'warning']:
        level_mode = '{}_mode'.format(level)
        level_min = '{}_min'.format(level)
        level_max = '{}_max'.format(level)
        metric[level_mode] = metric.get(level_mode, 'outside')
        metric[level_min] = metric.get(level_min, None)
        metric[level_max] = metric.get(level_max, None)

        if metric[level_mode] == 'outside':
            # metric must be outside the range...
            if metric[level_min] is not None and metric['value'] >= metric[level_min]:
                # metric is higher than minimum...
                if metric[level_max] is not None:
                    # there is a maximum set...
                    if metric['value'] < metric[level_max]:
                        # Metric is higher than minimum and lower than the maximum...
                        return statuses[level]
                else:
                    # No maximum set, and metric is higher than minimum
                    return statuses[level]
        else:
            # inside
            if metric[level_min] is not None and metric['value'] < metric[level_min]:
                # minimum is set, and metric is below it
                return statuses[level]
            if metric[level_max] is not None and metric['value'] > metric[level_max]:
                # maximum is set and metric is above it
                return statuses[level]

    # If none of the checks apply, then the metric is okay
    return 'OK'

def choose_maximum_status(minimum_status, proposed_status):
    if minimum_status == 'OK':
        return proposed_status
    if minimum_status == 'Warning' and proposed_status == 'Critical':
        return proposed_status
    return minimum_status

def work_out_status_changes(executable, new_statuses):
    global check_database
    changes = []
    for check, new in new_statuses.items():
        logger.debug('Changes: {}'.format(check))
        try:
            logger.debug('Config: {}'.format(check_config['check_config'][check]))
            repeat_config = check_config['check_config'][check].get('repeat', 0)
        except KeyError:
            logger.debug('No config')
            repeat_config = 0

        new['timestamp'] = datetime.now(timezone.utc)
        new['status_reason'] = "Check '{}' set the state to {}".format(check, new['status'])

        try:
            old = check_database[check]
        except KeyError:
            old = new

        metric_change = {}

        if 'metrics' in new:
            # find the 'worst' metric
            for key, info in new['metrics'].items():
                metric_status = check_metric_in_range(info)
                new_check_status = choose_maximum_status(metric_change.get('status', 'OK'), metric_status)
                if new_check_status != metric_change.get('status', 'OK'):
                    metric_change['status'] = new_check_status
                    metric_change['status_reason'] = "Check '{}' metric '{}' set the state to {}".format(check, key, new_check_status)
                    metric_change['metric'] = key

        # We now have the check status, and maybe a metric status. See if the
        # worst of those two is different than the old status
        worst_status = choose_maximum_status(new['status'], metric_change.get('status', 'OK'))
        if worst_status != old['status']:
            # There's a change to status...
            if repeat_config > 0:
                # We have to do 'n' checks in a row before the state actually changes
                try:
                    current_count = old['repeat_count']
                except KeyError:
                    current_count = 0
                current_count = current_count + 1
                if current_count >= repeat_config:
                    # We've done enough repeat checks, state is actually changing
                    changes.append({
                        'check': check,
                        'from_state': old['status'],
                        'to_state': metric_change.get('status', new['status']),
                        'change_reason': metric_change.get('status_reason', new['status_reason']),
                        'timestamp': new['timestamp'],
                        'repeat_count': repeat_config,
                    })
                    new['status'] = metric_change.get('status', new['status'])
                    new['status_reason'] = metric_change.get('status_reason', new['status_reason'])
                    new['repeat_count'] = repeat_config
                    for key in ['soft_status', 'soft_status_reason']:
                        if key in new:
                            del new[key]
                else:
                    # Problem exists, but we're not changing state just yet
                    new['repeat_count'] = current_count
                    new['soft_status'] = metric_change.get('status', new['status'])
                    new['soft_status_reason'] = metric_change.get('status_reason', new['status_reason'])
                    new['status'] = old['status']
                    new['status_reason'] = old['status_reason']
            else:
                # No repeat config, so change state immediately
                changes.append({
                    'check': check,
                    'from_state': old['status'],
                    'to_state': metric_change.get('status', new['status']),
                    'change_reason': metric_change.get('status_reason', new['status_reason']),
                    'timestamp': new['timestamp'],
                })
                new['status'] = metric_change.get('status', new['status'])
                new['status_reason'] = metric_change.get('status_reason', new['status_reason'])
        else:
            # No *change* to status, just set it as needed
            new['status'] = metric_change.get('status', new['status'])
            new['status_reason'] = metric_change.get('status_reason', new['status_reason'])

        check_database[check] = new

    return changes

def run_action(executable, arguments):
    result = subprocess.run([executable] + arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if result.stderr:
        logger.warning("Action '{}' emitted some STDERR: {}".format(executable, result.stderr))

    if result.stdout:
        stdout = result.stdout.decode('utf-8')
        logger.info("Action '{}' emitted some STDOUT: {}".format(executable, stdout))

    return result.returncode

# Run any configured actions on changes to states
def action_changes(changes):
    global check_config
    action_keys = {
        'OK': 'action_ok',
        'Warning': 'action_warning',
        'Critical': 'action_critical',
    }
    for change in changes:
        check = change['check']
        if check in check_config['check_config']:
            my_config = check_config['check_config'][check]
            executable = None
            arguments = []
            key_name = 'action'

            for key in [action_keys[change['to_state']], 'action']:
                try:
                    executable = my_config[key]['executable']
                    arguments = my_config[key].get('arguments', [])
                    key_name = key
                    break
                except KeyError:
                    continue

            if executable is not None:
                out = run_action(executable, arguments)
                logger.info("Action '{}' for check '{}' after state change from {} to {} returned {}".format(key_name, check, change['from_state'], change['to_state'], out))

def executable_runner():
    last_state_save_time = datetime.min.replace(tzinfo=pytz.UTC)
    while [ 1 ]:
        # Look at the first check, and work out how long to wait until we should run it
        try:
            then_time = executable_database[0]['next_check']
        except IndexError:
            # No checks!
            time.sleep(10)
            continue

        exec_diff = then_time - datetime.now(timezone.utc)
        if exec_diff.total_seconds() < 0.1:
            logger.debug("Running executable {}".format(executable_database[0]))
            new_status = run_executable(executable_database[0])
            changes = work_out_status_changes(executable_database[0], new_status)
            action_changes(changes)
            pop_and_reinsert_executable()
            continue

        save_diff = datetime.now(timezone.utc) - last_state_save_time
        if save_diff.total_seconds() > 50:
            save_state()
            if config_args.monchero_server is not None:
                send_state_to_server()
            last_state_save_time = datetime.now(timezone.utc)

        # Recalculate the wait time so we take into account any time used above
        exec_diff = then_time - datetime.now(timezone.utc)
        if exec_diff.total_seconds() > 0.1:
            logger.debug("sleeping for half of {} (them={})".format(exec_diff.total_seconds(), then_time))
            time.sleep(exec_diff.total_seconds() / 2)

def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""

    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError ("Type %s not serializable" % type(obj))

def save_state():
    data = {
        'version': VERSION,
        'hostname': our_hostname,
        'timestamp': datetime.now(timezone.utc).astimezone().isoformat(),
        'checks': check_database,
    }
    state_filename = "{}/state.json".format(config_args.data_directory)
    try:
        with open(state_filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4, default=json_serial)
    except OSError as e:
        logger.critical("Could not write to state file {}: {}".format(state_filename, str(e)))
    except TypeError as e:
        logger.error('Could not serialise the state to save it: {}'.format(str(e)))

def send_state_to_server():
    protocol = 'https'
    if not config_args.monchero_server_tls:
        protocol = 'http'

    data = {
        'version': VERSION,
        'hostname': our_hostname,
        'timestamp': datetime.now(timezone.utc).astimezone().isoformat(),
        'checks': check_database,
    }

    # We can't use requests json input here
    try:
        data_string = json.dumps(data, default=json_serial)
    except TypeError as e:
        logger.error('Could not serialise the state to POST it: {}'.format(str(e)))
        return

    print("Then time = {} now = {}".format(executable_database[0]['next_check'], datetime.now(timezone.utc)))
    try:
        r = requests.post('{}://{}/api/submit_state'.format(protocol, config_args.monchero_server), data=data_string, timeout=config_args.monchero_server_timeout)
    except requests.exceptions.RequestException as e:
        logger.error('Could not POST to {}://{}: {}'.format(protocol, config_args.monchero_server, str(e)))

def load_check_configs():
    global check_config

    if not os.path.isdir(config_args.check_config_path):
        logger.debug('Check config path ({}) is not a directory'.format(config_args.check_config_path))
        return

    for filename in os.listdir(config_args.check_config_path):
        parsed = {}
        try:
            full_path = os.path.join(config_args.check_config_path, filename)
            with open(full_path, 'r') as f:
                try:
                    parsed = yaml.load(f, Loader=yaml.SafeLoader)
                except yaml.parser.ParserError as e:
                    logger.warning('Could not parse config {}: {}'.format(full_path, str(e)))
                    continue
        except IOError as e:
            logger.warning('Could not read check config {}: {}'.format(full_path, str(e)))
            continue

        # parsed can be None if the file is empty or just comments
        if parsed is not None:
            for key in check_config.keys():
                if key in parsed:
                    # Merge the parsed config into our own
                    check_config[key] = {**check_config[key], **parsed[key]}

def get_our_hostname():
    tries = []
    tries.append(socket.gethostname())
    tries.append(socket.getfqdn())
    tries.append(os.uname().nodename)

    for item in tries:
        # If it's got at least one dot in it, maybe it's an FQDN...?
        if '.' in item:
            return item

    # No idea what to do, try the most likely to be useful
    return tries[0]

def main(argv=None):
    global config_args, logger, our_hostname

    our_hostname = get_our_hostname()

    parser = configargparse.ArgumentParser(
        default_config_files=['/etc/monchero.conf', './monchero.conf']
    )
    parser.add('-c', '--agent-config-path', is_config_file=True, help='Path to the agent configuration file', env_var='MONCHERO_CONFIG_PATH')
    parser.add('-e', '--check-config-path', default='/etc/monchero.d', help='Path to a directory of check configs', env_var='MONCHERO_CHECK_CONFIG_PATH')
    parser.add('-i', '--interval', default=60, type=int, help='Set the default execution interval (in seconds)', env_var='MONCHERO_INTERVAL')
    parser.add('-l', '--log-level', default='info', choices=['debug','info','warning','error','critical'], help='Set the log verbosity level', env_var='MONCHERO_LOG_LEVEL')
    parser.add('-d', '--data-directory', default='/var/monchero-agent', help='The path to a directory to write data files', env_var='MONCHERO_DATA_DIRECTORY')
    parser.add('-n', '--node-name', default=our_hostname, help='Set the hostname, rather than using the detected one', env_var='MONCHERO_HOSTNAME')
    parser.add('--monchero-plugin-directory', default='/usr/lib/monchero/plugins', help='The directory to look for Monchero check plugins', env_var='MONCHERO_PLUGIN_DIRECTORY')
    parser.add('--checkmk-plugin-directory', default='/usr/lib/check_mk_agent/local/', help='The directory to look for CheckMK local plugins', env_var='MONCHERO_CHECKMK_PLUGIN_DIRECTORY')
    parser.add('--script-checks-directory', default='/usr/lib/monchero/scripts', help='The directory to look for plain script checks', env_var='MONCHERO_SCRIPT_CHECKS_DIRECTORY')
    parser.add('-m', '--monchero-server', default=None, help='The poller or server to which the agent will send status', env_var='MONCHERO_SERVER')
    parser.add('--monchero-server-tls', default=True, type=bool, help='Use TLS to send to the Monchero server', env_var='MONCHERO_SERVER_TLS')
    parser.add('--monchero-server-timeout', default=30, type=int, help='The number of seconds timeout when sending to the Monchero server', env_var='MONCHERO_SERVER_TIMEOUT')

    config_args = parser.parse_args()

    logging_format = '%(message)s'
    if config_args.log_level == 'debug':
        logging_format = '(%(funcName)s) {}'.format(logging_format)
    logging_format = '[%(levelname)s] {}'.format(logging_format)
    if sys.stdin and sys.stdin.isatty():
        logging_format = '%(asctime)s {}'.format(logging_format)

    logging.basicConfig(format=logging_format, level=config_args.log_level.upper())
    logger = logging.getLogger()

    our_hostname = config_args.node_name

    try:
        load_check_configs()
        initialise_executables(config_args.monchero_plugin_directory, 'native')
        initialise_executables(config_args.checkmk_plugin_directory, 'checkmk')
        initialise_executables(config_args.script_checks_directory, 'script')
        initialise_commands()
        executable_runner()
    except KeyboardInterrupt:
        print("Stopped")
    return(0)

if __name__ == "__main__":
    sys.exit(main())

### Unit tests below here

# Run these with: python3 -m unittest monchero-agent.py
import unittest

logger = logging.getLogger()
logger.level = logging.DEBUG
stream_handler = logging.StreamHandler(sys.stderr)
logger.addHandler(stream_handler)

class TestCase(unittest.TestCase):
    def test_one(self):
        assert state_wash('OK') == 'OK', "Should return OK"
        assert state_wash('Warning') == 'Warning'
        assert state_wash('Critical') == 'Critical'
        assert state_wash('Unknown') == 'Unknown'
        assert state_wash('ok') == 'OK'
        assert state_wash('warning') == 'Warning'
        assert state_wash('critical') == 'Critical'
        assert state_wash('unknown') == 'Unknown'
        assert state_wash('0') == 'OK'
        assert state_wash(0) == 'OK'
        assert state_wash('gribblechops') == None

    def test_parse_nagios_range(self):
        assert parse_nagios_range('10') == (10, None, 'outside')
        assert parse_nagios_range('10:20') == (10, 20, 'outside')
        assert parse_nagios_range('~:20') == (None, 20, 'outside')
        assert parse_nagios_range('@10:20') == (10, 20, 'inside')
        assert parse_nagios_range('-20:-10') == (-20, -10, 'outside')
        self.assertRaises(ValueError, parse_nagios_range, '10:-10')

    def test_parse_nagios_metric(self):
        test_data = {
            '12.34': { 'value': 12.34 },
            '1;10;20': { 'value': 1, 'warning_min': 10, 'critical_min': 20 },
            '0.025030s;;;0.000000': { 'value': 0.025030 },
            '123;10:20;;;': { 'value': 123, 'warning_min': 10, 'warning_max': 20},
            '456;10:20;30:40;50;60': { 'value': 456, 'warning_min': 10, 'warning_max': 20, 'critical_min': 30, 'critical_max': 40}
        }
        for test, expected in test_data.items():
            actual = parse_nagios_metric(test)
            for key, value in expected.items():
                assert actual[key] == value, 'Test: {} {} == {} (got: {})'.format(test, key, value, actual[key])

    def test_parse_nagios_output_string(self):
        in_string = 'HTTP OK: HTTP/1.1 200 OK - 659 bytes in 0.025 second response time |time=0.025030s;;;0.000000 size=659B;;;0'
        message = 'HTTP OK: HTTP/1.1 200 OK - 659 bytes in 0.025 second response time'
        metrics = {'size': {'value': 659}, 'time': {'value': 0.02503}}
        self.assertEqual( (message, metrics), parse_nagios_output_string(in_string))
        assert parse_nagios_output_string('hello') == ('hello', {})

    def test_parse_checkmk_output(self):
        test_cases = [
            {
                'input': '0 bacula_backups - OK because This host does not particpate in regular backups\nExtended messages',
                'output': {'bacula_backups': {'message': 'OK because This host does not particpate in regular backups', 'metrics': {}, 'status': 0 }},
            },
            {
                'input': '0 memcache connect_ms=5.274295806884766|set_get_delete_ms=7.222652435302734 Connected in 5.27 mS, set/get/delete in 7.22 mS',
                'output': {'memcache': {'message': 'Connected in 5.27 mS, set/get/delete in 7.22 mS', 'metrics': {'connect_ms': {'value': 5.274295806884766}, 'set_get_delete_ms': {'value': 7.222652435302734}}, 'status': 0}},
            },
            {
                'input': '0 "nginx threads" ActiveConn=1|reading=0|writing=1|waiting=0 OK - ActiveConn:1 reading:0 writing:1 waiting:0',
                'output': {'nginx threads': {'message': 'OK - ActiveConn:1 reading:0 writing:1 waiting:0', 'metrics': {'ActiveConn': {'value': 1}, 'reading': {'value': 0}, 'waiting': {'value': 0}, 'writing': {'value': 1}}, 'status': 0}},
            },
            {
                'input': '0 some_check ms=15;10;20 Some message',
                'output': {'some_check': {'message': 'Some message', 'metrics': {'ms': {'value': 15, 'warning_min': 10, 'warning_max': None, 'warning_mode': 'outside', 'critical_min': 20, 'critical_max': None, 'critical_mode': 'outside'}}, 'status': 0 }},
            },
        ]
        executable = { 'filename': '/some/file/name' }
        for case in test_cases:
            self.assertEqual( parse_checkmk_output(case['input'], executable), case['output'])


    def test_choose_maximum_status(self):
        assert choose_maximum_status('OK', 'Warning') == 'Warning'
        assert choose_maximum_status('OK', 'Critical') == 'Critical'
        assert choose_maximum_status('Warning', 'OK') == 'Warning'
        assert choose_maximum_status('Warning', 'Warning') == 'Warning'
        assert choose_maximum_status('Warning', 'Critical') == 'Critical'
        assert choose_maximum_status('Critical', 'OK') == 'Critical'
        assert choose_maximum_status('Critical', 'Warning') == 'Critical'
        assert choose_maximum_status('Critical', 'Critical') == 'Critical'

    def test_check_metric_in_range(self):
        assert check_metric_in_range({'value':20,'warning_min':80,'warning_max':None}) == 'OK'
        assert check_metric_in_range({'value':80,'warning_min':80,'warning_max':None}) == 'Warning'
        assert check_metric_in_range({'value':9999,'warning_min':80,'warning_max':None}) == 'Warning'
        assert check_metric_in_range({'value':40,'warning_min':20,'warning_max':30}) == 'OK'
        assert check_metric_in_range({'value':20,'critical_min':80,'critical_max':None}) == 'OK'
        assert check_metric_in_range({'value':80,'critical_min':80,'critical_max':None}) == 'Critical'
        assert check_metric_in_range({'value':9999,'critical_min':80,'critical_max':None}) == 'Critical'
        assert check_metric_in_range({'value':40,'critical_min':20,'critical_max':30}) == 'OK'
        assert check_metric_in_range({'value': 100, 'warning_min': 80}) == 'Warning'

    def test_to_number(self):
        assert to_number('123') == 123
        assert to_number('123.45') == 123.45
        assert to_number(123) == 123
        assert to_number(123.45) == 123.45
        assert to_number("-55") == -55
        assert to_number("-55.55") == -55.55
        self.assertRaises(ValueError, to_number, {})
        self.assertRaises(ValueError, to_number, '123.45.56')
