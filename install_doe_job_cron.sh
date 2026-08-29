#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
log_dir="$repo_dir/job_tracker/logs"
python_bin="$(command -v python3)"
mkdir -p "$log_dir"

cron_line="15 7 * * * cd $(printf '%q' "$repo_dir") && $(printf '%q' "$python_bin") doe_job_scraper.py --output-dir job_tracker/output >> $(printf '%q' "$log_dir")/daily.log 2>&1 # doe-lab-job-tracker"
(crontab -l 2>/dev/null | grep -v 'doe-lab-job-tracker'; echo "$cron_line") | crontab -
echo "Installed daily job tracker at 07:15 local time."
