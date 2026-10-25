#!/usr/bin/env bash
# Screening driver: tier-1 score -> CLAP shortlist -> tier-2 CLAP -> rescore -> stage-2 detailed fit.
set -e
cd /home/user/test
PY=/opt/ml/bin/python
A=work/catalog/analysis
CAT=work/catalog/provisional.jsonl
ARGS="work/analysis/juice_pitch.json work/analysis/reine_live_chroma.npy work/analysis/reine_clap.npy"
$PY pipeline/catalog/score_catalog.py $CAT $A $ARGS work/catalog/scored_t1.jsonl --no-vibe > work/catalog/scored_t1.log 2>&1
# shortlist for CLAP: top 1200 overall + top 100 per source + every reference track
$PY - <<'P'
import json, collections
rows=[json.loads(l) for l in open("work/catalog/scored_t1.jsonl")]
ids=[r["id"] for r in rows[:1200]]
per=collections.defaultdict(list)
for r in rows: per[r["source"]].append(r["id"])
for s,l in per.items(): ids+=l[:100]
ids+=[json.loads(l)["id"] for l in open("work/catalog/provisional.jsonl") if json.loads(l).get("is_reference")]
ids=list(dict.fromkeys(ids))
open("work/catalog/ids_tier2.txt","w").write("\n".join(ids)+"\n")
print(len(ids),"ids for tier 2")
P
OMP_NUM_THREADS=1 $PY pipeline/catalog/analyze_catalog.py $CAT $A --workers 4 --ids work/catalog/ids_tier2.txt >> work/catalog/analysis_t2.log 2>&1
$PY pipeline/catalog/score_catalog.py $CAT $A $ARGS work/catalog/scored.jsonl > work/catalog/scored.log 2>&1
$PY pipeline/catalog/fit_detailed.py work/catalog/scored.jsonl 300 work/catalog/fit_detailed.jsonl > work/catalog/fit_detailed.log 2>&1
echo "screening done"
