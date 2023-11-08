#!/bin/bash

# Required parameters passed in by run.js
server=$1
output_dir=$2

# Script paramters
num_users=$3
server_name=$4
setup_type=$5
user_generation=$6

echo Setting up $server_name...
echo Using arguments: num_users=$num_users, server=$server, output_dir=$output_dir, \
server_name=$server_name, setup_type=$setup_type, user_generation=$user_generation

# Server setup
ssh root@$server 'bash -s' < scripts/$server_name-setup.sh $server $setup_type

# Local setup
trial=`basename $output_dir`
mkdir -p $output_dir
mkdir -p $output_dir/../../../users/$num_users/$trial

if [ "$user_generation" = "generate-users" ]; then
    node generate_users.js $num_users > $output_dir/../../../users/$num_users/$trial/users_log.txt
    node generate_rooms.js > $output_dir/../../../users/$num_users/$trial/rooms_log.txt
    cp users.csv $output_dir/../../../users/$num_users/$trial/users.csv
    cp rooms.json $output_dir/../../../users/$num_users/$trial/rooms.json
else # copy-users
    cp $output_dir/../../../users/$num_users/$trial/users.csv users.csv
    cp $output_dir/../../../users/$num_users/$trial/rooms.json rooms.json
fi
