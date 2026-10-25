#!/usr/bin/env bash
# Like jobqueue.sh, but exits as soon as the queue is empty (a finite run instead of a resident runner).
Q=/home/user/test/work/queue
touch $Q/pending.txt $Q/done.txt
while true; do
  exec 9>$Q/.lock; flock 9
  job=$(head -n 1 $Q/pending.txt)
  [ -n "$job" ] && sed -i '1d' $Q/pending.txt
  flock -u 9
  [ -z "$job" ] && break
  [ "$job" = "STOP" ] && break
  echo "[$(date -u +%H:%M:%S)] START $job" >> $Q/done.txt
  bash -c "$job" >> $Q/jobs.log 2>&1
  echo "[$(date -u +%H:%M:%S)] END rc=$? $job" >> $Q/done.txt
done
echo "[$(date -u +%H:%M:%S)] DRAINED" >> $Q/done.txt
