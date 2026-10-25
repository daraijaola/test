#!/usr/bin/env bash
# Append one job (all args joined) to the serial compute queue.
Q=/home/user/test/work/queue; exec 9>$Q/.lock; flock 9; echo "$*" >> $Q/pending.txt
