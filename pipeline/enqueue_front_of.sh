#!/usr/bin/env bash
# Insert one job into the serial queue just before the first pending line containing PATTERN
# (appends when nothing matches). Usage: enqueue_front_of.sh PATTERN JOB...
Q=/home/user/test/work/queue; exec 9>$Q/.lock; flock 9
pat="$1"; shift
/opt/ml/bin/python -I - "$Q/pending.txt" "$pat" "$*" <<'PY'
import sys
p, pat, job = sys.argv[1:4]
lines = [l.rstrip("\n") for l in open(p) if l.strip()]
i = next((k for k, l in enumerate(lines) if pat in l), len(lines))
lines.insert(i, job)
open(p, "w").write("\n".join(lines) + "\n")
PY
