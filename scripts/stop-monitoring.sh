#!/bin/bash

# Required parameters passed in by run.py
server=$1
output_dir=$2

# Script paramters
output_name=$3
remove_tokens=$4

# Server commands

# Restore persisted pid for pcp termination
ssh root@$server "kill -9 \`cat /matrix/tmp_pcp_pid\`; yes | rm /matrix/tmp_pcp_pid"

# Local commands
scp root@$server:/matrix/pcp_$output_name.csv $output_dir/pcp_$output_name.csv

# Clean up files on server after copying
ssh root@$server "yes | rm /matrix/pcp_$output_name.csv"

if [ "$remove_tokens" = "remove-tokens" ]; then
    yes | rm tokens.csv
fi
