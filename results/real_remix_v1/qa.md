# End-to-end questions on real ledgers (SemEval-2016 stance tweets)

A = how many tweets mention an entity (gold: text match); B = % of those against the target (gold: labels).

| method | A: median relative error | A: within 20% | B: mean abs error (pts) | $ per question |
|---|---|---|---|---|
| ledger | 59% | 0% | 16.1 | $0.097 |
| ledger+census | 0% | 86% | 5.3 | $0.189 |
| rag20 | 75% | 0% | 27.2 | $0.028 |
| rag100 | 52% | 14% | 16.9 | $0.056 |

Census checker vs text-match gold: precision 0.94, recall 1.00; reader chose scope=all in 7/7 questions.

| target | entity | gold A/B | ledger | ledger+census | rag20 | rag100 |
|---|---|---|---|---|---|---|
| ledger_atheism_remix | freethinker | 17 / 12% | 7 / 14% | 19 / 0% | 3 / 10% | 10 / 0% |
| ledger_atheism_remix | god | 56 / 38% | 70 / 50% | 56 / 32% | 85 / 65% | 85 / 30% |
| ledger_atheism_remix | lovewins | 12 / 0% | 6 / 33% | 12 / 0% | 3 / 67% | 6 / 10% |
| ledger_feminist_remix | feminist | 38 / 37% | 95 / 66% | 58 / 45% | 70 / 55% | 32 / 50% |
| ledger_feminist_remix | yesallwomen | 13 / 15% | 10 / 30% | 13 / 15% | 6 / 35% | 6 / 35% |
| ledger_feminist_remix | gamergate | 12 / 58% | 4 / 70% | 12 / 70% | 3 / 90% | 5 / 100% |
| ledger_hillary_remix | hillaryclinton | 17 / 35% | 55 / 45% | 17 / 35% | 8 / 60% | 7 / 50% |
