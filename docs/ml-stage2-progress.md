# ML stage 2 progress

Validation complete: 2026-10-25. Status: PARTIALLY_READY.
Report: [ml-stage2-report.md](ml-stage2-report.md).
Instructions: [ml-quick-check.md](ml-quick-check.md).
Aggregate evidence: [ml-stage2-results.json](ml-stage2-results.json).

- Final suite:106 passed,0 failed,0 skipped,91.11s.
- 49 changed Python files pass Ruff and formatting; staged diff check passes.
- Official full FNS:6835377 documents,7594 XML/CRC,188031 unique regional companies.
  Combined with Excel:188040 companies and63 projects.
- Full PostgreSQL17.11/PostGIS3.6.2 import committed:188040 companies,
  188790 matches,63 projects,139 needs,188435 snapshots,188853 source records.
- All five HTTP endpoints plus NULL-score case pass on the full corpus;
  heatmap395 cells; unknown presence/growth preserved.
- Independent-process repeat committed:0 new companies/projects; ALL six table
  counts unchanged. No duplicate INN/source groups, invented finance,
  coordinates, probabilities or confirmed initiator links.
- NLP126 inferred recommendations/13 abstentions in both methods;3 semantic
  signals. E5 optional; threshold.84 and business weights unchanged.
- Expert sheets63 projects/dev21/test42; labels empty; evaluation not_evaluated.
- No critical implementation defects identified by available checks.

Raw data, private review sheets, models, credentials and scratch scripts remain
in ignored backend/ml/artifacts/. Test and demo databases are distinct and marked.

Branch:feature/ml-stage2-validation. User authorized ordinary commit/push after
validation. Actual published SHA is identified by Git history/remote refs;
no PR, merge or force-push is part of this task.

External remaining work:expert ratings, verified initiator IDs, financial/presence/
sales data, frontend nullable-field integration by its owner.
