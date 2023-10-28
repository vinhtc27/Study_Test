#!/bin/env python3

import argparse
import datetime
import json
import multiprocessing
import os

from argparse import Namespace

# Define JSON test schema and set default parameters
TEST_SCHEMA = {
    "name": None,
    "script": None,
    "pre_script_command": None,
    "pre_script_command_args": None,
    "post_script_command": None,
    "post_script_command_args": None,
    "num_users": None,
    "spawn_rate": None,
    "runtime": None,
    "autoquit": 5,
    "output_dir": os.getcwd()
}

def num_workers_checker(value):
    ivalue = int(value)
    if ivalue <= 0:
        raise argparse.ArgumentTypeError(f"{value} is an invalid positive integer value")

    return ivalue

def run_script(args, json=None):
    script_path = args.path

    # Add http(s):// prefix if not provided
    if not (args.host is None):
        host = args.host if args.host.startswith("http://") or args.host.startswith("https://") \
                         else f"https://{args.host}"

    if not (json is None):
        if (args.host is None) or (json.num_users is None) or \
            (json.spawn_rate is None) or (json.runtime is None):
            raise KeyError("Missing either '--host' argument or one of the following json " \
                           "fields: 'num_users', 'spawn_rate', or 'runtime'")
        script_path = json.script

    # Start up locust worker background processes
    for i in range(args.num_workers):
        os.system(f"locust -f {script_path} --headless --worker &")

    # Start up master process
    master_command = f"locust -f {script_path}"
    master_command += " --master"
    master_command += f" --expect-workers {args.num_workers}"
    master_command += " --csv-full-history"

    if json is None:
        master_command += f" --csv {args.output_dir}/{args.name}.csv"
        master_command += f" --html {args.output_dir}/{args.name}.html"

        if not (args.host is None):
            master_command += f" --host {host}"
    else:
        master_command += " --autostart"
        master_command += f" --csv {json.output_dir}/{json.name}.csv"
        master_command += f" --html {json.output_dir}/{json.name}.html"
        master_command += f" --host {host}"
        master_command += f" --users {json.num_users}"
        master_command += f" --spawn-rate {json.spawn_rate}"
        master_command += f" --run-time {json.runtime}"
        master_command += "" if json.autoquit is None else f" --autoquit {json.autoquit}"

    os.system(master_command)

    # Terminate background worker processes (do not always terminate on CTRL-C)
    os.system("killall locust")

parser = argparse.ArgumentParser(description="Runs a matrix load-test")
parser.add_argument("path", type=str,
                    help="Path to the locust python script or json test-suite")
parser.add_argument("-n", "--num_workers", type=num_workers_checker,
                    default=multiprocessing.cpu_count(), nargs="?",
                    help="Amount of workers to use. Defaults to amount of available CPU threads.")
parser.add_argument("--host", type=str, nargs="?",
                    help="URL to host server (e.g. 'www.example.com' or 'http://www.example.com')")
parser.add_argument("-o", "--output_dir", type=str, nargs="?", default=os.getcwd(),
                    help="Path to store csv and html data")
parser.add_argument("--name", type=str, nargs="?", default="locust",
                    help="Path to store csv and html data")

args = parser.parse_args()

if not args.path.endswith(".json"):
    run_script(args)
else:
    # Run all tests defined in the test suite
    with open(args.path, "r", encoding="utf-8") as file:
        test_suite_dict = json.load(file)
        test_suite = Namespace(**test_suite_dict)

        for test_dict in test_suite.scripts:
            # Define script schema to allow for omitting entries if desired
            test_dict_json = TEST_SCHEMA.copy()
            test_dict_json.update(test_dict)
            test = Namespace(**test_dict_json)

            if not (test.pre_script_command is None):
                print(f"[{datetime.datetime.now()}] Running pre-script command(s): {test.pre_script_command}")

                for script, script_args in zip(test.pre_script_command, test.pre_script_command_args):
                    command = f"{script} {args.host} {test.output_dir} {script_args}"
                    os.system(command)

            print(f"[{datetime.datetime.now()}] Running script: {test.script}")
            run_script(args, test)

            if not (test.post_script_command is None):
                print(f"[{datetime.datetime.now()}] Running post-script command(s): {test.post_script_command}")

                for script, script_args in zip(test.post_script_command, test.post_script_command_args):
                    command = f"{script} {args.host} {test.output_dir} {script_args}"
                    os.system(command)

            #print(test)
