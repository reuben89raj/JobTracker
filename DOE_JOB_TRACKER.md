# DOE Laboratory Job Tracker

The tracker is tailored to Reuben Samson Raj's profile: programmable networks,
cyber/ICS security, smart grids, distributed systems, cloud-native engineering,
and HPC systems. It searches official DOE-lab career sources using multiple
research-role queries, deduplicates the results, fetches each posting, and
writes a dated CSV plus `doe_jobs_latest.csv`.

Implemented sources:

- ORNL: server-rendered career search.
- ANL, BNL, NREL: Workday CXS JSON APIs behind JavaScript-heavy portals.
- PNNL: Jibe JSON jobs API behind its careers portal.
- LLNL: public LLNL career search with SmartRecruiters apply links.

It excludes postings that explicitly mention security clearance or classified
work. It also requires computing relevance and excludes postings with physics,
materials, chemistry, biological, geology, or similar non-computing domains in
the title; description-only domain matches are excluded unless the posting has
at least two computing indicators. A result labelled
`not_mentioned_verify_with_employer` is **not** proof that no
clearance/background requirement exists; check the official posting before
applying.

## Run now

    python3 doe_job_scraper.py --output-dir job_tracker/output

Outputs:

- `job_tracker/output/doe_jobs_latest.csv`
- `job_tracker/output/doe_jobs_YYYY-MM-DD.csv`
- `job_tracker/output/last_run.json`: scrape timestamp, source health, and errors.
- `job_tracker/output/excluded/doe_jobs_latest.csv`: audit trail of excluded roles.
- Local dashboard state lives in `job_tracker/dashboard.sqlite3`.

These generated files are ignored by git and recreated by the scraper/dashboard
when needed.

Optional federal DOE/NETL coverage requires a USAJOBS API key:

    export USAJOBS_API_KEY='...'
    python3 doe_job_scraper.py --include-usajobs --output-dir job_tracker/output

## Schedule daily

Review then run:

    chmod +x install_doe_job_cron.sh
    ./install_doe_job_cron.sh

It installs a user crontab entry for 07:15 local time and appends output to
`job_tracker/logs/daily.log`. It does not install a system-wide cron job.
