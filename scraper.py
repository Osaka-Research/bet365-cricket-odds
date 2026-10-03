#!/usr/bin/env python3
"""
bet365 cricket odds scraper.

Renders the page with a real browser (Playwright) because bet365 is a
client-side SPA — the raw HTML response has no odds data in it.

Requires:
    pip install playwright
    playwright install chromium

Usage:
    python3 scraper.py                     # one-shot scrape, prints table
    python3 scraper.py --json out.json      # save as JSON
    python3 scraper.py --csv out.csv        # save as CSV
    python3 scraper.py --interval 60        # poll every 60s, ctrl-C to stop
    python3 scraper.py --headed             # show the browser window (debug)
    python3 scraper.py --debug-dump dump.html
        # save the fully-rendered HTML so you can inspect real class names
        # in a browser devtools and fix SELECTOR_* below if bet365 changed
        # their markup (they rotate obfuscated class names periodically).

Notes:
    - bet365's ToS prohibits automated access. Use for personal reference
      only, keep request/poll rate low, and stop if you hit a captcha or
      block page.
    - Odds/market layout differs by region (bet365 geo-redirects). If the
      page shows a different sport list or language, adjust BET365_URL.
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BET365_URL = "https://www.bet365.com/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# These are the known-common bet365 class prefixes for the sportsbook
# grid as of recent public scraper references. bet365 changes these
# periodically — if extraction returns nothing, run with --debug-dump
# and update the three selectors below to match the live markup.
SELECTOR_COOKIE_ACCEPT = "#onetrust-accept-btn-handler"
SELECTOR_CRICKET_NAV = "text=Cricket"
SELECTOR_FIXTURE_CONTAINER = "div.gl-MarketGroupContainer"
SELECTOR_TEAM_NAME = "div.rcl-ParticipantFixtureDetailsHigher_Team, div.rcl-ParticipantFixtureDetails_Team"
SELECTOR_ODDS = "span.gl-ParticipantOddsOnly_Odds, span.gl-Participant_Odds"


def scrape_once(headless: bool, debug_dump: str | None) -> list[dict]:
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(user_agent=USER_AGENT, viewport={"width": 1400, "height": 1000})
        page.goto(BET365_URL, wait_until="domcontentloaded", timeout=30000)

        # cookie banner, if present
        try:
            page.click(SELECTOR_COOKIE_ACCEPT, timeout=5000)
        except PWTimeout:
            pass

        # navigate to cricket
        try:
            page.click(SELECTOR_CRICKET_NAV, timeout=15000)
        except PWTimeout:
            print("Could not find 'Cricket' nav link — page layout may have "
                  "changed, or you're geo-redirected to a different site "
                  "variant. Try --debug-dump to inspect.", file=sys.stderr)

        # let odds grid render
        page.wait_for_timeout(4000)

        if debug_dump:
            with open(debug_dump, "w", encoding="utf-8") as f:
                f.write(page.content())
            print(f"Rendered HTML saved to {debug_dump}")

        fixtures = page.query_selector_all(SELECTOR_FIXTURE_CONTAINER)
        scraped_at = datetime.now(timezone.utc).isoformat()

        for fixture in fixtures:
            teams = [t.inner_text().strip() for t in fixture.query_selector_all(SELECTOR_TEAM_NAME)]
            odds = [o.inner_text().strip() for o in fixture.query_selector_all(SELECTOR_ODDS)]
            if not teams or not odds:
                continue
            results.append({
                "scraped_at": scraped_at,
                "teams": teams,
                "odds": odds,
            })

        browser.close()
    return results


def write_json(rows: list[dict], path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)


def write_csv(rows: list[dict], path: str):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["scraped_at", "teams", "odds"])
        for r in rows:
            writer.writerow([r["scraped_at"], " vs ".join(r["teams"]), " | ".join(r["odds"])])


def print_table(rows: list[dict]):
    if not rows:
        print("No fixtures scraped. Selectors may be stale — try --debug-dump.")
        return
    for r in rows:
        print(f"{' vs '.join(r['teams']):<40} {' | '.join(r['odds'])}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--headed", action="store_true", help="show browser window instead of headless")
    ap.add_argument("--json", metavar="PATH", help="write results to JSON file")
    ap.add_argument("--csv", metavar="PATH", help="write results to CSV file")
    ap.add_argument("--interval", type=int, metavar="SECONDS", help="poll repeatedly at this interval")
    ap.add_argument("--debug-dump", metavar="PATH", help="save rendered HTML for selector debugging")
    args = ap.parse_args()

    def run_once():
        rows = scrape_once(headless=not args.headed, debug_dump=args.debug_dump)
        print_table(rows)
        if args.json:
            write_json(rows, args.json)
            print(f"Saved JSON: {args.json}")
        if args.csv:
            write_csv(rows, args.csv)
            print(f"Saved CSV: {args.csv}")
        return rows

    if args.interval:
        try:
            while True:
                run_once()
                print(f"--- sleeping {args.interval}s ---")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("Stopped.")
    else:
        run_once()


if __name__ == "__main__":
    main()
