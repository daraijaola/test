#!/usr/bin/env bash
# Serial compute queue: heavy PyTorch jobs oversubscribe a 4-core box badly when run together,
# so every CPU-heavy step is appended to work/queue/pending.txt and executed here one at a time.
# Each line is a shell command. A line "STOP" ends the runner.
Q=/home/user/test/work/queue
touch $Q/pending.txt $Q/done.txt
while true; do
  exec 9>$Q/.lock; flock 9
  job=$(head -n 1 $Q/pending.txt)
  [ -n "$job" ] && sed -i '1d' $Q/pending.txt
  flock -u 9
  if [ -z "$job" ]; then sleep 10; continue; fi
  [ "$job" = "STOP" ] && break
  echo "[$(date -u +%H:%M:%S)] START $job" >> $Q/done.txt
  bash -c "$job" >> $Q/jobs.log 2>&1
  echo "[$(date -u +%H:%M:%S)] END rc=$? $job" >> $Q/done.txt
done
