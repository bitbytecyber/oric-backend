#!/usr/bin/env bash
# Import the yearly HEC ORIC workbooks (FY 2019-20 .. FY 2025-26) into a deployed portal.
#
# Run on the server, after the code with these commands is deployed (migrations run by the deploy):
#
#   HEC_DIR=~/oric_hec ./import_hec_history.sh            # dry run: report only, rolls everything back
#   HEC_DIR=~/oric_hec MODE=apply ./import_hec_history.sh  # for real
#
# HEC_DIR holds hec_2019-20.xlsx ... hec_2025-26.xlsx (the files in data/, renamed). It is mounted read-only into
# a one-off backend container; nothing is copied into the image. Defaults target the Oracle dev box; override
# COMPOSE_FILE / ENV_FILE for another server.
#
# What it does
#   1. Prints what the server holds per fiscal year (records by source, workbook imports).
#   2. ensure_cycles: creates missing FY 2019-20 .. 2022-23 as CLOSED (also in a dry run; existing years untouched).
#   3. FY 2019-20 .. 2023-24: full workbook import (replaces only earlier *workbook* records of that year).
#   4. FY 2024-25: if it was already imported, keeps its records, re-dates the ones the old parser mis-yeared and
#      stores its "as submitted" Score Card; otherwise imports it.
#   5. FY 2025-26: imports with B.xi read from the "Uploade PC" sheet. Records entered in the portal are kept;
#      set CLEAR_2026=1 to first delete EVERY FY 2025-26 record (only if they are demo/test data).
set -euo pipefail

COMPOSE_FILE=${COMPOSE_FILE:-/home/ubuntu/bitbytecyber/ned_oric_backend/docker/docker-compose.dev.yml}
ENV_FILE=${ENV_FILE:-/home/ubuntu/bitbytecyber/ned_oric_backend/config/.env.dev}
HEC_DIR=${HEC_DIR:?set HEC_DIR to the folder with hec_<FY>.xlsx}
MODE=${MODE:-dry}
CLEAR_2026=${CLEAR_2026:-0}

HEC_DIR=$(cd "$HEC_DIR" && pwd)
for fy in 2019-20 2020-21 2021-22 2022-23 2023-24 2024-25 2025-26; do
  [[ -f "$HEC_DIR/hec_$fy.xlsx" ]] || { echo "missing $HEC_DIR/hec_$fy.xlsx" >&2; exit 1; }
done
[[ $MODE == dry || $MODE == apply ]] || { echo "MODE must be dry or apply" >&2; exit 1; }

manage() {
  docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" run --rm -T \
    -v "$HEC_DIR:/app/.local/hec:ro" backend python manage.py "$@"
}
dry() { [[ $MODE == dry ]] && echo "--dry-run" || true; }

report() {
  manage shell -c '
from django.db.models import Count
from imports.models import ImportBatch
from org.models import ReportingCycle
from submissions.models import Submission
for c in ReportingCycle.objects.order_by("year"):
    subs = Submission.objects.filter(cycle=c)
    by_source = dict(subs.values_list("source").annotate(n=Count("id")).values_list("source", "n"))
    batches = list(ImportBatch.objects.filter(cycle=c, kind="hec_workbook", status="applied")
                   .values_list("pk", flat=True))
    demo = subs.filter(data__has_key="_demo").count()
    print(f"{c.label:11} {c.status:7} records {subs.count():5} {by_source}  demo {demo}  workbook imports {batches}")
'
}

echo "== $MODE run against $COMPOSE_FILE"
echo "== before"
report

echo "== fiscal years"
manage ensure_cycles --from 2020 --to 2026

for pair in 2019-20:2020 2020-21:2021 2021-22:2022 2022-23:2023 2023-24:2024; do
  fy=${pair%:*}; year=${pair#*:}
  echo "== FY $fy"
  manage import_hec_workbook "/app/.local/hec/hec_$fy.xlsx" --year "$year" $(dry)
done

echo "== FY 2024-25"
batch_2025=$(manage shell -c '
from imports.models import ImportBatch
b = (ImportBatch.objects.filter(cycle__year=2025, kind="hec_workbook", status="applied")
     .exclude(stats__has_key="only").order_by("-created_at").first())
print(b.pk if b else "")' | tail -n 1 | tr -d '\r')
if [[ -n $batch_2025 ]]; then
  echo "already imported (batch #$batch_2025): records kept"
  manage repair_import_dates --batch "$batch_2025" $([[ $MODE == apply ]] && echo --apply || true)
  manage import_hec_workbook /app/.local/hec/hec_2024-25.xlsx --year 2025 --card-only $(dry)
else
  manage import_hec_workbook /app/.local/hec/hec_2024-25.xlsx --year 2025 $(dry)
fi

echo "== FY 2025-26"
if [[ $CLEAR_2026 == 1 ]]; then
  if [[ $MODE == apply ]]; then manage clear_cycle --year 2026 --yes; else manage clear_cycle --year 2026 --dry-run; fi
fi
manage import_hec_workbook /app/.local/hec/hec_2025-26.xlsx --year 2026 --sheet "B.xi=Uploade PC" $(dry)

echo "== after"
report
