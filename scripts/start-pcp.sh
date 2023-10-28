#!/bin/bash

# Script paramters
output_name=$1

# Start metrics collection and store PID for later termination
# Have to share pid across shell sessions, so store pid in temp file
nohup pmrep -o csv \
    kernel.all.load \
    swap.used \
    mem.util.free \
    mem.util.bufmem \
    mem.util.cached \
    swap.pagesin \
    swap.pagesout \
    disk.all.blkread \
    disk.all.blkwrite \
    kernel.all.intr \
    kernel.all.pswitch \
    kernel.all.cpu.nice \
    kernel.all.cpu.user \
    kernel.all.cpu.intr \
    kernel.all.cpu.sys \
    kernel.all.cpu.idle \
    kernel.all.cpu.wait.total \
    kernel.all.cpu.steal \
    network.tcpconn.established \
    network.all.in.bytes \
    network.all.in.packets \
    network.all.out.bytes \
    network.all.out.packets \
    > /matrix/pcp_$output_name.csv 2>&1 & echo $! > /matrix/tmp_pcp_pid
