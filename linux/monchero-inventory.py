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
from pathlib import Path

VERSION="0.0.1"

config_args = None
logger = None

# Generally we try to skip hidden or obvious backup files
def is_backup_file(filename):
    if filename.startswith('.') or filename.endswith('.bak') or filename.endswith('.rpmsave') or filename.endswith('.old') or filename.endswith('.orig'):
        return True
    return False

def perform_inventory(lib_dir):
    rel = Path(lib_dir)
    lib_dir = rel.absolute()
    if not os.path.isdir(lib_dir):
        logger.debug('Library directory {} does not exist'.format(lib_dir))
        return

    # Start with ordinary executables
    executables = [
        f for f in os.listdir(lib_dir) if os.path.isfile(os.path.join(lib_dir, f)) and os.access(os.path.join(lib_dir, f),os.X_OK)
    ]

    inventory = []

    for executable in executables:
        # Skip hidden files and common backup suffixes
        if is_backup_file(executable):
            continue
        filename = os.path.join(lib_dir, executable)

        filename = os.path.normpath(filename)

        result = subprocess.run(filename, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            # Successful
            inventory.append(filename)

    return inventory

def save_inventory(inventory):
    for item in inventory:
        filename = os.path.basename(item)
        dest = os.path.join(config_args.monchero_plugin_directory, filename)
        logger.debug("Inventory item: {} - {}".format(item, dest))

        try:
            link = os.readlink(dest)
            if link == item:
                # Already exists and is correct
                logger.debug("link for {} is already okay".format(dest))
                continue
            else:
                # Is a symlink to the wrong place
                logger.debug("link = {} item = {}".format(link, item))
                logger.warning("Could not overwrite symlink at {}".format(dest))
                continue
        except FileNotFoundError:
            # This is okay
            pass
        except OSError:
            # Is not a symlink
            logger.warning("Could not overwrite existing file: {}".format(dest))
            continue

        #print("Added symlink")
        os.symlink(item, dest)
    return

def main(argv=None):
    global config_args, logger

    parser = configargparse.ArgumentParser()
    parser.add('--plugin-lib-directory', default='/usr/lib/monchero/lib', help='The directory containing the library of checks')
    parser.add('--monchero-plugin-directory', default='/usr/lib/monchero/plugins', help='The directory to look for Monchero check plugins', env_var='MONCHERO_PLUGIN_DIRECTORY')

    parser.add('-l', '--log-level', default='info', choices=['debug','info','warning','error','critical'], help='Set the log verbosity level', env_var='MONCHERO_LOG_LEVEL')
    parser.add('--version', action='store_true', help='Returns the version of the agent and quits')

    config_args = parser.parse_args()

    if config_args.version:
        print("{}".format(VERSION))
        sys.exit(0)

    logging_format = '%(message)s'
    if config_args.log_level == 'debug':
        logging_format = '(%(funcName)s) {}'.format(logging_format)
    logging_format = '[%(levelname)s] {}'.format(logging_format)
    if sys.stdin and sys.stdin.isatty():
        logging_format = '%(asctime)s {}'.format(logging_format)

    logging.basicConfig(format=logging_format, level=config_args.log_level.upper())
    logger = logging.getLogger()

    try:
        inventory = perform_inventory(config_args.plugin_lib_directory)
        save_inventory(inventory)
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

