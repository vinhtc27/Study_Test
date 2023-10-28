#!/bin/bash

# Script paramters
small_host=$1
large_host=$2

# Small server
python3 run.py --host $small_host test-suites/synapse-sqlite-100.json; sleep 60
python3 run.py --host $small_host test-suites/synapse-postgres-noworkers-100.json; sleep 60
python3 run.py --host $small_host test-suites/dendrite-sqlite-100.json; sleep 60
python3 run.py --host $small_host test-suites/conduit-sqlite-100.json; sleep 60

python3 run.py --host $small_host test-suites/synapse-sqlite-200.json; sleep 60
python3 run.py --host $small_host test-suites/synapse-postgres-noworkers-200.json; sleep 60
python3 run.py --host $small_host test-suites/dendrite-sqlite-200.json; sleep 60
python3 run.py --host $small_host test-suites/conduit-sqlite-200.json; sleep 60

python3 run.py --host $small_host test-suites/synapse-sqlite-500.json; sleep 60
python3 run.py --host $small_host test-suites/synapse-postgres-noworkers-500.json; sleep 60
python3 run.py --host $small_host test-suites/dendrite-sqlite-500.json; sleep 60
python3 run.py --host $small_host test-suites/conduit-sqlite-500.json; sleep 60

python3 run.py --host $small_host test-suites/synapse-sqlite-1k.json; sleep 60
python3 run.py --host $small_host test-suites/synapse-postgres-noworkers-1k.json; sleep 60
python3 run.py --host $small_host test-suites/dendrite-sqlite-1k.json; sleep 60
python3 run.py --host $small_host test-suites/conduit-sqlite-1k.json; sleep 60

# Large server
python3 run.py --host $large_host test-suites/synapse-1k.json; sleep 60
python3 run.py --host $large_host test-suites/dendrite-1k.json; sleep 60
python3 run.py --host $large_host test-suites/conduit-1k.json; sleep 60

python3 run.py --host $large_host test-suites/synapse-2k.json; sleep 60
python3 run.py --host $large_host test-suites/dendrite-2k.json; sleep 60
python3 run.py --host $large_host test-suites/conduit-2k.json; sleep 60

python3 run.py --host $large_host test-suites/synapse-5k.json; sleep 60
python3 run.py --host $large_host test-suites/dendrite-5k.json; sleep 60
python3 run.py --host $large_host test-suites/conduit-5k.json; sleep 60

python3 run.py --host $large_host test-suites/synapse-10k.json; sleep 60
python3 run.py --host $large_host test-suites/dendrite-10k.json; sleep 60
python3 run.py --host $large_host test-suites/conduit-10k.json; sleep 60
