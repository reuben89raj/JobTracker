#!/usr/bin/env python3
"""Local interactive dashboard for the DOE job tracker."""

import argparse
import csv
import json
import sqlite3
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
DEFAULT_CSV = ROOT / "job_tracker" / "output" / "doe_jobs_latest.csv"
DEFAULT_DB = ROOT / "job_tracker" / "dashboard.sqlite3"
PERSONAL_STATUSES = ("untracked", "applied", "in_progress", "not_proceeding")


def database_connection(path):
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            record_id TEXT PRIMARY KEY,
            laboratory TEXT NOT NULL,
            title TEXT NOT NULL,
            location TEXT,
            posted_date TEXT,
            closing_date TEXT,
            url TEXT NOT NULL,
            profile_match_score INTEGER,
            clearance_status TEXT,
            technical_fit_status TEXT,
            computing_evidence TEXT,
            description TEXT,
            source_status TEXT NOT NULL DEFAULT 'open',
            personal_status TEXT NOT NULL DEFAULT 'untracked',
            notes TEXT NOT NULL DEFAULT '',
            first_seen_utc TEXT NOT NULL,
            last_seen_utc TEXT NOT NULL,
            updated_utc TEXT NOT NULL
        )
    """)
    connection.commit()
    return connection


def sync_csv(connection, csv_path):
    if not csv_path.exists():
        return 0
    now = datetime.now(timezone.utc).isoformat()
    connection.execute("UPDATE jobs SET source_status = 'closed'")
    with csv_path.open(newline="") as source:
        for row in csv.DictReader(source):
            connection.execute("""
                INSERT INTO jobs (
                    record_id, laboratory, title, location, posted_date, closing_date, url,
                    profile_match_score, clearance_status, technical_fit_status, computing_evidence,
                    description, source_status, first_seen_utc, last_seen_utc, updated_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                    laboratory=excluded.laboratory, title=excluded.title, location=excluded.location,
                    posted_date=excluded.posted_date, closing_date=excluded.closing_date, url=excluded.url,
                    profile_match_score=excluded.profile_match_score,
                    clearance_status=excluded.clearance_status,
                    technical_fit_status=excluded.technical_fit_status,
                    computing_evidence=excluded.computing_evidence,
                    description=excluded.description, source_status='open', last_seen_utc=excluded.last_seen_utc,
                    updated_utc=excluded.updated_utc
            """, (
                row["record_id"], row["laboratory"], row["title"], row["location"],
                row["posted_date"], row["closing_date"], row["url"],
                int(row["profile_match_score"] or 0), row["clearance_screening_status"],
                row["technical_fit_status"], row["computing_match_evidence"], row["description"],
                now, now, now,
            ))
    connection.commit()
    return connection.execute("SELECT COUNT(*) FROM jobs WHERE source_status = 'open'").fetchone()[0]


def serialize(row):
    return dict(row)


def last_run_status(csv_path):
    status_path = csv_path.parent / "last_run.json"
    if not status_path.exists():
        return {}
    try:
        return json.loads(status_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


class DashboardHandler(SimpleHTTPRequestHandler):
    database = None
    csv_path = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def json_response(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/jobs":
            self.handle_jobs(parse_qs(parsed.query))
            return
        if parsed.path == "/api/summary":
            self.handle_summary()
            return
        if parsed.path == "/api/sync":
            self.handle_sync()
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_PATCH(self):
        prefix = "/api/jobs/"
        record_id = self.path[len(prefix):] if self.path.startswith(prefix) else ""
        if not record_id or "/" in record_id:
            self.json_response({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(size))
        except (ValueError, json.JSONDecodeError):
            self.json_response({"error": "invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return
        status = payload.get("personal_status")
        if status not in PERSONAL_STATUSES:
            self.json_response({"error": f"personal_status must be one of {PERSONAL_STATUSES}"}, HTTPStatus.BAD_REQUEST)
            return
        self.database.execute(
            "UPDATE jobs SET personal_status=?, notes=?, updated_utc=? WHERE record_id=?",
            (status, str(payload.get("notes", "")), datetime.now(timezone.utc).isoformat(), record_id),
        )
        self.database.commit()
        row = self.database.execute("SELECT * FROM jobs WHERE record_id=?", (record_id,)).fetchone()
        if row is None:
            self.json_response({"error": "job not found"}, HTTPStatus.NOT_FOUND)
            return
        self.json_response(serialize(row))

    def handle_sync(self):
        count = sync_csv(self.database, self.csv_path)
        self.json_response({"open_jobs": count, "source": str(self.csv_path)})

    def handle_summary(self):
        sync_csv(self.database, self.csv_path)
        status = last_run_status(self.csv_path)
        source = dict(self.database.execute(
            "SELECT source_status, COUNT(*) AS count FROM jobs GROUP BY source_status"
        ).fetchall())
        personal = dict(self.database.execute(
            "SELECT personal_status, COUNT(*) AS count FROM jobs GROUP BY personal_status"
        ).fetchall())
        laboratories = [row[0] for row in self.database.execute(
            "SELECT DISTINCT laboratory FROM jobs ORDER BY laboratory"
        ).fetchall()]
        self.json_response({
            "source": source,
            "personal": personal,
            "laboratories": laboratories,
            "source_health": status.get("sources", []),
            "generated_at_utc": status.get("generated_at_utc", ""),
            "errors": status.get("errors", []),
        })

    def handle_jobs(self, query):
        sync_csv(self.database, self.csv_path)
        source_status = query.get("source_status", ["open"])[0]
        personal_status = query.get("personal_status", ["all"])[0]
        laboratory = query.get("laboratory", ["all"])[0]
        search = query.get("q", [""])[0].strip()
        limit = min(max(int(query.get("limit", ["100"])[0]), 1), 250)
        clauses, values = [], []
        if source_status != "all":
            clauses.append("source_status = ?")
            values.append(source_status)
        if personal_status != "all":
            clauses.append("personal_status = ?")
            values.append(personal_status)
        if laboratory != "all":
            clauses.append("laboratory = ?")
            values.append(laboratory)
        if search:
            clauses.append("(title LIKE ? OR laboratory LIKE ? OR location LIKE ? OR description LIKE ?)")
            values.extend([f"%{search}%"] * 4)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.database.execute(
            f"SELECT * FROM jobs {where} ORDER BY source_status='open' DESC, profile_match_score DESC, title LIMIT ?",
            (*values, limit),
        ).fetchall()
        self.json_response({"jobs": [serialize(row) for row in rows], "count": len(rows)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    args.database.parent.mkdir(parents=True, exist_ok=True)
    connection = database_connection(args.database)
    sync_csv(connection, args.csv)
    DashboardHandler.database = connection
    DashboardHandler.csv_path = args.csv
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Dashboard running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
