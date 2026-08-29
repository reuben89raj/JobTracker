#!/usr/bin/env python3
"""Collect DOE-lab research job postings matching Reuben Samson Raj's profile."""

import argparse
import csv
import hashlib
import html
import json
import os
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

import requests


DEFAULT_QUERIES = (
    "postdoctoral network security",
    "postdoctoral cyber security",
    "research associate smart grid",
    "research scientist programmable networks",
    "research scientist distributed systems",
    "research scientist HPC security",
    "scientist industrial control systems",
    "research scientist cloud native",
)
ROLE_TERMS = ("postdoctoral", "postdoc", "research associate", "research scientist", "scientist")
ENGINEER_TERMS = ("engineer", "architect", "developer")
PROFILE_TERMS = (
    "network", "security", "cyber", "programmable", "p4", "smart grid", "energy",
    "industrial control", "critical infrastructure", "distributed systems", "cloud", "hpc",
    "systems", "kubernetes", "software",
)
COMPUTING_TERMS = (
    "computer science", "computer engineering", "network", "cyber", "software",
    "distributed systems", "distributed computing", "cloud", "kubernetes", "hpc",
    "high-performance computing", "systems", "operating system", "programming",
    "data science", "machine learning", "artificial intelligence", "p4",
    "programmable", "industrial control", "smart grid", "cybersecurity",
)
NONCOMPUTING_DOMAIN_TERMS = (
    "physics", "plasma", "materials science", "materials engineering", "materials",
    "chemical engineering", "chemistry", "chemical", "geology", "geoscience",
    "biological", "biology", "biomedical", "nuclear physics", "quantum chemistry",
)
CLEARANCE_TERMS = (
    "security clearance", "q clearance", "l clearance", "clearance required",
    "clearance requirement", "classified environment", "classified work",
    "able to obtain and maintain a clearance", "eligible for a security clearance",
)
USER_AGENT = "DOE-Lab-Job-Tracker/1.0 (personal research job tracking)"
WORKDAY_SOURCES = (
    {
        "laboratory": "ANL",
        "base_url": "https://argonne.wd1.myworkdayjobs.com",
        "tenant": "argonne",
        "site": "Argonne_Careers",
    },
    {
        "laboratory": "BNL",
        "base_url": "https://bnl.wd1.myworkdayjobs.com",
        "tenant": "bnl",
        "site": "Externa",
    },
    {
        "laboratory": "NREL",
        "base_url": "https://nrel.wd5.myworkdayjobs.com",
        "tenant": "nrel",
        "site": "NLR",
    },
)
HTML_SOURCES = (
    {
        "laboratory": "LLNL",
        "platform": "smartrecruiters_html",
        "search_url": "https://www.llnl.gov/join-our-team/careers/find-your-job?search={query}",
    },
)
PNNL_SOURCE = {
    "laboratory": "PNNL",
    "platform": "jibe_json",
    "api_url": "https://careers.pnnl.gov/api/jobs?page={page}&keywords={query}",
}


class ORNLSearchParser(HTMLParser):
    """Extract unique desktop result links from ORNL's server-rendered search page."""

    def __init__(self):
        super().__init__()
        self.jobs = []
        self._href = None
        self._collect = False
        self._text = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a" and "jobTitle-link" in attributes.get("class", ""):
            self._href = attributes.get("href")
            self._collect = True
            self._text = []

    def handle_data(self, data):
        if self._collect:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._collect:
            title = " ".join("".join(self._text).split())
            if self._href and title:
                self.jobs.append((title, self._href))
            self._href = None
            self._collect = False


class PageParser(HTMLParser):
    """Collect visible text and JSON-LD JobPosting blocks from a job page."""

    def __init__(self):
        super().__init__()
        self.text = []
        self.json_ld = []
        self._inside_json_ld = False
        self._json_buffer = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "script" and attributes.get("type", "").lower() == "application/ld+json":
            self._inside_json_ld = True
            self._json_buffer = []
        elif tag in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_data(self, data):
        if self._inside_json_ld:
            self._json_buffer.append(data)
        elif not self._skip_depth:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._inside_json_ld:
            self.json_ld.append("".join(self._json_buffer))
            self._inside_json_ld = False
        elif tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1


def fetch(url, timeout):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json"})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def fetch_json(url, timeout, method="GET", payload=None):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if method == "POST":
        response = requests.post(url, json=payload or {}, headers=headers, timeout=timeout)
    else:
        response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


def clean_text(value):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())


def job_posting_data(page_html):
    parser = PageParser()
    parser.feed(page_html)
    for raw_json in parser.json_ld:
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            continue
        entries = payload if isinstance(payload, list) else payload.get("@graph", [payload])
        for entry in entries:
            if isinstance(entry, dict) and entry.get("@type") == "JobPosting":
                return entry, clean_text(" ".join(parser.text))
    return {}, clean_text(" ".join(parser.text))


def relevance_score(title, description):
    text = f"{title} {description}".lower()
    return sum(term in text for term in PROFILE_TERMS)


def clearance_status(description):
    text = description.lower()
    matches = [term for term in CLEARANCE_TERMS if term in text]
    if matches:
        return "excluded_clearance_or_classified", "; ".join(matches)
    return "not_mentioned_verify_with_employer", "no clearance/classified requirement found in fetched posting"


def computing_fit(title, description):
    title_text = title.lower()
    text = f"{title} {description}".lower()
    computing_matches = [term for term in COMPUTING_TERMS if term in text]
    noncomputing_matches = [term for term in NONCOMPUTING_DOMAIN_TERMS if term in text]
    title_noncomputing_matches = [term for term in NONCOMPUTING_DOMAIN_TERMS if term in title_text]
    if title_noncomputing_matches:
        return "excluded_noncomputing_title", "; ".join(title_noncomputing_matches), "; ".join(computing_matches)
    if noncomputing_matches and len(computing_matches) < 2:
        return "excluded_noncomputing_domain", "; ".join(noncomputing_matches), "; ".join(computing_matches)
    if not computing_matches:
        return "excluded_no_computing_match", "", ""
    return "computing_fit", "; ".join(noncomputing_matches), "; ".join(computing_matches)


def parse_ornl(queries, timeout):
    found = {}
    for query in queries:
        search_url = f"https://jobs.ornl.gov/search/?q={quote(query)}"
        parser = ORNLSearchParser()
        parser.feed(fetch(search_url, timeout))
        for title, relative_url in parser.jobs:
            url = urljoin(search_url, relative_url)
            found[url] = title
    return [("ORNL", title, url) for url, title in found.items()]


def parse_workday(source, queries, timeout, page_size=20, max_pages=8):
    found = {}
    search_url = f"{source['base_url']}/wday/cxs/{source['tenant']}/{source['site']}/jobs"
    for query in queries:
        offset = 0
        for _ in range(max_pages):
            payload = {"limit": page_size, "offset": offset, "searchText": query}
            data = fetch_json(search_url, timeout, method="POST", payload=payload)
            postings = data.get("jobPostings", [])
            for posting in postings:
                external_path = posting.get("externalPath")
                if not external_path:
                    continue
                found[external_path] = posting
            offset += page_size
            if offset >= int(data.get("total", 0)) or not postings:
                break
    return [(source, posting) for posting in found.values()]


def workday_record(source, posting, timeout):
    external_path = posting["externalPath"]
    detail_url = f"{source['base_url']}/wday/cxs/{source['tenant']}/{source['site']}{external_path}"
    detail = fetch_json(detail_url, timeout)
    info = detail.get("jobPostingInfo", {})
    location = info.get("location") or info.get("jobRequisitionLocation", {}).get("descriptor", "")
    posted_date = info.get("postedOn") or info.get("posted", "")
    url = info.get("externalUrl") or f"{source['base_url']}/en-US/{source['site']}{external_path}"
    return {
        "laboratory": source["laboratory"],
        "title": info.get("title") or posting.get("title", ""),
        "url": url,
        "location": location or posting.get("locationsText", ""),
        "posted_date": posted_date,
        "closing_date": info.get("endDate", ""),
        "description": clean_text(info.get("jobDescription", "")),
    }


def parse_llnl(queries, timeout):
    found = {}
    for source in HTML_SOURCES:
        for query in queries:
            search_url = source["search_url"].format(query=quote(query))
            page = fetch(search_url, timeout)
            for block in re.findall(r'<div class="row job-post">(.*?)</div>\s*</div>', page, flags=re.S):
                title_match = re.search(r'<a href="([^"]*/find-your-job/[^"]+)">([^<]+)</a>', block)
                apply_match = re.search(r'<a href="(https://jobs\.smartrecruiters\.com/LLNL/[^"]+)"', block)
                smalls = [clean_text(match) for match in re.findall(r"<small[^>]*>(.*?)</small>", block, flags=re.S)]
                if not title_match:
                    continue
                title = clean_text(title_match.group(2))
                url = apply_match.group(1) if apply_match else urljoin(search_url, title_match.group(1))
                location, posted_date = "", ""
                if len(smalls) > 1:
                    parts = [part.strip() for part in smalls[1].split("|")]
                    if len(parts) >= 2:
                        location = parts[1]
                    if len(parts) >= 3:
                        posted_date = parts[2]
                found[url] = {
                    "laboratory": source["laboratory"],
                    "title": title,
                    "url": url,
                    "location": location,
                    "posted_date": posted_date,
                    "closing_date": "",
                    "description": clean_text(f"{title} {' '.join(smalls)}"),
                }
    return list(found.values())


def parse_pnnl(queries, timeout, max_pages=5):
    found = {}
    for query in queries:
        for page in range(1, max_pages + 1):
            api_url = PNNL_SOURCE["api_url"].format(page=page, query=quote(query))
            data = fetch_json(api_url, timeout)
            jobs = data.get("jobs", [])
            for job in jobs:
                record = job.get("data", {})
                req_id = record.get("req_id")
                if req_id:
                    found[req_id] = record
            if not jobs:
                break
    return list(found.values())


def pnnl_record(job):
    description = " ".join(
        clean_text(job.get(field, ""))
        for field in ("description", "responsibilities", "qualifications")
        if job.get(field)
    )
    return {
        "laboratory": "PNNL",
        "title": job.get("title", ""),
        "url": f"https://careers.pnnl.gov/jobs/{job.get('req_id', '')}",
        "location": job.get("full_location", ""),
        "posted_date": job.get("posted_date", ""),
        "closing_date": job.get("posting_expiry_date", ""),
        "description": description,
    }


def enrich_llnl_record(record, timeout):
    try:
        _, visible_text = job_posting_data(fetch(record["url"], timeout))
        if visible_text:
            record["description"] = clean_text(visible_text)
    except Exception:
        pass
    return record


def parse_usajobs(keywords, timeout, api_key):
    if not api_key:
        return []
    url = (
        "https://data.usajobs.gov/api/search?Organization=DN&ResultsPerPage=500"
        f"&Keyword={quote(','.join(keywords))}"
    )
    request = Request(url, headers={"User-Agent": USER_AGENT, "Authorization-Key": api_key})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    records = []
    for item in payload["SearchResult"]["SearchResultItems"]:
        descriptor = item["MatchedObjectDescriptor"]
        title = descriptor["PositionTitle"]
        locations = "; ".join(location["LocationName"] for location in descriptor.get("PositionLocationDisplay", []) if isinstance(location, dict))
        records.append(("USAJOBS-DOE", title, descriptor["PositionURI"], locations, descriptor.get("PublicationStartDate", ""), descriptor.get("ApplicationCloseDate", ""), descriptor.get("UserArea", {}).get("Details", {}).get("JobSummary", "")))
    return records


def ornl_record(title, url, timeout):
    posting, visible_text = job_posting_data(fetch(url, timeout))
    description = clean_text(posting.get("description", visible_text))
    location = posting.get("jobLocation", "")
    if isinstance(location, dict):
        location = location.get("address", {}).get("addressLocality", "")
    if not location:
        location_match = re.search(r"Location:\s*(.*?)\s+Company:", description)
        location = location_match.group(1) if location_match else ""
    posted_date = posting.get("datePosted", "")
    if not posted_date:
        posted_match = re.search(r"Date:\s*([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})", description)
        posted_date = posted_match.group(1) if posted_match else ""
    return {
        "laboratory": "ORNL",
        "title": posting.get("title", title),
        "url": url,
        "location": location,
        "posted_date": posted_date,
        "closing_date": posting.get("validThrough", ""),
        "description": description,
    }


def normalize_record(record):
    title = record["title"]
    description = record["description"]
    status, evidence = clearance_status(description)
    fit_status, noncomputing_evidence, computing_evidence = computing_fit(title, description)
    record.update({
        "role_match": any(term in title.lower() for term in ROLE_TERMS),
        "profile_match_score": relevance_score(title, description),
        "clearance_screening_status": status,
        "clearance_screening_evidence": evidence,
        "technical_fit_status": fit_status,
        "computing_match_evidence": computing_evidence,
        "noncomputing_domain_evidence": noncomputing_evidence,
        "record_id": hashlib.sha256(record["url"].encode()).hexdigest()[:16],
    })
    return record


def passes_screen(record):
    high_fit_computing_engineer = (
        any(term in record["title"].lower() for term in ENGINEER_TERMS) and
        record["profile_match_score"] >= 3 and
        record["technical_fit_status"] == "computing_fit"
    )
    return (
        (record["role_match"] or high_fit_computing_engineer) and
        record["profile_match_score"] >= 1 and
        record["clearance_screening_status"] != "excluded_clearance_or_classified" and
        record["technical_fit_status"] == "computing_fit"
    )


def write_csv(records, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date().isoformat()
    fields = [
        "record_id", "laboratory", "title", "location", "posted_date", "closing_date", "url",
        "role_match", "profile_match_score", "clearance_screening_status",
        "clearance_screening_evidence", "technical_fit_status", "computing_match_evidence",
        "noncomputing_domain_evidence", "description",
    ]
    for path in (output_dir / f"doe_jobs_{today}.csv", output_dir / "doe_jobs_latest.csv"):
        with path.open("w", newline="") as destination:
            writer = csv.DictWriter(destination, fieldnames=fields)
            writer.writeheader()
            writer.writerows(records)
    return output_dir / "doe_jobs_latest.csv"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("job_tracker/output"))
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--max-postings", type=int, default=150)
    parser.add_argument("--max-postings-per-source", type=int, default=50)
    parser.add_argument("--include-usajobs", action="store_true")
    parser.add_argument("--queries", nargs="+", default=DEFAULT_QUERIES)
    args = parser.parse_args()

    errors = []
    records = []
    excluded_records = []
    source_health = []

    def collect_source(label, platform, iterable, record_builder):
        discovered = kept = excluded = 0
        try:
            for item in iterable():
                if discovered >= args.max_postings_per_source:
                    break
                discovered += 1
                try:
                    record = normalize_record(record_builder(item))
                    if passes_screen(record):
                        records.append(record)
                        kept += 1
                    else:
                        excluded_records.append(record)
                        excluded += 1
                except Exception as error:
                    errors.append(f"{label} posting: {error}")
            source_health.append({
                "laboratory": label,
                "platform": platform,
                "status": "ok",
                "discovered": discovered,
                "kept": kept,
                "excluded": excluded,
            })
        except Exception as error:
            errors.append(f"{label} search: {error}")
            source_health.append({
                "laboratory": label,
                "platform": platform,
                "status": "error",
                "discovered": discovered,
                "kept": kept,
                "excluded": excluded,
                "error": str(error),
            })

    collect_source(
        "ORNL",
        "server_rendered_html",
        lambda: parse_ornl(args.queries, args.timeout),
        lambda item: ornl_record(item[1], item[2], args.timeout),
    )

    for workday_source in WORKDAY_SOURCES:
        collect_source(
            workday_source["laboratory"],
            "workday_cxs_json",
            lambda source=workday_source: parse_workday(source, args.queries, args.timeout),
            lambda item: workday_record(item[0], item[1], args.timeout),
        )

    collect_source(
        "LLNL",
        "smartrecruiters_html",
        lambda: parse_llnl(args.queries, args.timeout),
        lambda item: enrich_llnl_record(item, args.timeout),
    )

    collect_source(
        "PNNL",
        PNNL_SOURCE["platform"],
        lambda: parse_pnnl(args.queries, args.timeout),
        lambda item: pnnl_record(item),
    )

    if args.include_usajobs:
        try:
            usajobs_discovered = usajobs_kept = usajobs_excluded = 0
            for source, title, url, location, posted, closing, description in parse_usajobs(
                PROFILE_TERMS, args.timeout, os.environ.get("USAJOBS_API_KEY")
            ):
                usajobs_discovered += 1
                if usajobs_discovered > args.max_postings_per_source:
                    break
                record = normalize_record({
                    "laboratory": source, "title": title, "url": url, "location": location,
                    "posted_date": posted, "closing_date": closing, "description": clean_text(description),
                })
                if passes_screen(record):
                    records.append(record)
                    usajobs_kept += 1
                else:
                    excluded_records.append(record)
                    usajobs_excluded += 1
            source_health.append({
                "laboratory": "USAJOBS-DOE",
                "platform": "usajobs_api",
                "status": "ok",
                "discovered": usajobs_discovered,
                "kept": usajobs_kept,
                "excluded": usajobs_excluded,
            })
        except Exception as error:
            errors.append(f"USAJOBS: {error}")
            source_health.append({
                "laboratory": "USAJOBS-DOE",
                "platform": "usajobs_api",
                "status": "error",
                "discovered": 0,
                "kept": 0,
                "excluded": 0,
                "error": str(error),
            })

    records = sorted(
        {record["url"]: record for record in records}.values(),
        key=lambda row: (-row["profile_match_score"], row["laboratory"], row["title"]),
    )[:args.max_postings]
    latest = write_csv(records, args.output_dir)
    write_csv(excluded_records, args.output_dir / "excluded")
    status = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "records": len(records),
        "clearance_not_mentioned": sum(row["clearance_screening_status"] == "not_mentioned_verify_with_employer" for row in records),
        "excluded_clearance_or_classified": sum(
            row["clearance_screening_status"] == "excluded_clearance_or_classified"
            for row in excluded_records
        ),
        "excluded_records": len(excluded_records),
        "sources": source_health,
        "errors": errors,
    }
    (args.output_dir / "last_run.json").write_text(json.dumps(status, indent=2) + "\n")
    print(f"Wrote {len(records)} screened postings to {latest}")
    if errors:
        print(f"Completed with {len(errors)} source/posting errors; see {args.output_dir / 'last_run.json'}", file=sys.stderr)


if __name__ == "__main__":
    main()
