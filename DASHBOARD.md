# DOE Job Dashboard

Run the dashboard:

```bash
cd ~/Documents/JobTracker
python3 dashboard.py
```

Open `http://127.0.0.1:8765` in a browser. The dashboard reads the latest CSV
from `job_tracker/output/doe_jobs_latest.csv`, stores local job-state in
`job_tracker/dashboard.sqlite3`, and keeps your personal status and notes even
when the scraper refreshes the CSV.

Use the filters independently:

- Company/lab: ORNL, ANL, BNL, NREL, PNNL, LLNL, or all labs present in the latest CSV.
- Source status: Open, Closed, or All.
- Personal status: Untracked, Applied, In progress, Not proceeding, or All.

Set a job to `NA` and click Save to remove it from the active dashboard and
latest CSV. The dashboard writes discarded jobs to
`job_tracker/output/discarded_jobs.csv`; the scraper reads that file during
future cron runs and skips those postings.

Use the hamburger menu in the header to refresh the CSV, download the active
CSV, or view the discard pile.

The source-health chips report how many fetched postings each adapter kept
after the deterministic profile, technical-domain, and clearance screens.

The server listens only on `127.0.0.1` by default. Stop it with `Ctrl+C`.
