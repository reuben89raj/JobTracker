# DOE Job Tracker

Track DOE lab roles, keep your application status in one place, and run a
local dashboard over the latest scraped CSV.

## Quick Start

```bash
cd ~/Documents/JobTracker
python3 doe_job_scraper.py --output-dir job_tracker/output
python3 dashboard.py
```

Open `http://127.0.0.1:8765` in your browser.

## What It Does

- Scrapes DOE lab job boards and writes `doe_jobs_latest.csv`.
- Filters for computing-relevant jobs and excludes clearance/classified roles.
- Saves your personal status and notes in local dashboard storage.

## Repo Notes

- Generated CSVs, SQLite files, logs, caches, and local PDFs are ignored by git.
- See [DOE_JOB_TRACKER.md](./DOE_JOB_TRACKER.md) for scraper details.
- See [DASHBOARD.md](./DASHBOARD.md) for dashboard usage.
