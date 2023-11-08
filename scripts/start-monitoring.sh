#!/bin/bash

# Required parameters passed in by run.js
server=$1
output_dir=$2

# Script paramters
output_name=$3

# Server commands
ssh root@$server 'bash -s' < scripts/start-pcp.sh $output_name
