"""Check the deployed API and site after every deploy: health, refusals, CORS, "Buka di BPS" links, the per-client limit with a forged
X-Forwarded-For, and the site's security headers and API address. Exit 1 on any failure.

    uv run python scripts/check_live.py https://api-....run.app [https://cari-data-bps.netlify.app]

The limit check sends 25 searches, so run it at most once a minute.
"""

import html
import re
import sys
import time

import httpx

failures = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{'' if ok else ': ' + detail}")
    if not ok:
        failures.append(name)


def api_checks(api, site):
    c = httpx.Client(base_url=api, timeout=90)
    r = c.get("/api/health")
    check("health", r.status_code == 200 and r.json() == {"ok": True}, f"{r.status_code} {r.text[:80]}")
    check("search refuses one letter", c.get("/api/search", params={"q": "a"}).status_code == 422)
    check("search refuses 201 characters", c.get("/api/search", params={"q": "a" * 201}).status_code == 422)
    check("feedback refuses a NaN body", c.post("/api/feedback", content="NaN", headers={"Content-Type": "application/json"}).status_code == 422)
    check("value refuses an unknown table", c.get("/api/value", params={"doc_id": "var:0000:nope"}).status_code == 404)
    r = c.get("/api/search", params={"q": "jumlah penduduk miskin kabupaten garut"})
    check("search answers with results", r.status_code == 200 and len(r.json()["results"]) == 5, f"{r.status_code} {r.text[:80]}")
    if site:
        allowed = c.options("/api/search", headers={"Origin": site, "Access-Control-Request-Method": "GET"})
        check("CORS allows the site", allowed.headers.get("access-control-allow-origin") == site, str(allowed.headers.get("access-control-allow-origin")))
    other = c.options("/api/search", headers={"Origin": "https://example.com", "Access-Control-Request-Method": "GET"})
    check("CORS refuses another origin", "access-control-allow-origin" not in other.headers)
    link_checks(c)
    codes = [c.get("/api/search", params={"q": "inflasi riau"}, headers={"X-Forwarded-For": f"203.0.113.{i}"}).status_code for i in range(25)]
    check("a forged X-Forwarded-For does not lift the per-client limit", 429 in codes, f"codes {sorted(set(codes))}")


def link_checks(c):
    """"Buka di BPS" of press releases and publications opens the page of that title. Table pages fill in with
    JavaScript after loading, so a plain request cannot tell whether they work: those need a browser."""
    found = []
    for q in ("perkembangan pariwisata bali", "publikasi statistik indonesia 2026"):
        found += [r for r in c.get("/api/search", params={"q": q}).json()["results"] if r["url"]]
    links = [r for kind in ("pressrelease", "publication") for r in [r for r in found if r["type"] == kind][:2]]
    check("search finds press releases and publications to check", len(links) == 4, str([r["type"] for r in links]))
    bps = httpx.Client(timeout=30, headers={"User-Agent": "bps-data-finder/0.1 (link check)"})
    for item in links:
        time.sleep(3)  # bps.go.id answers 429 to fast visitors
        r = bps.get(item["url"])
        title = html.unescape((re.search(r"<title>([^<]*)</title>", r.text) or [None, ""])[1])
        check(f"{item['type']} link opens its page", r.status_code == 200 and item["title"][:40].lower() in title.lower(), f"{r.status_code} {item['url']}")


def site_checks(site, api):
    c = httpx.Client(timeout=30)
    r = c.get(site)
    check("site answers", r.status_code == 200, str(r.status_code))
    h = r.headers
    csp = h.get("content-security-policy", "")
    check("CSP allows only this API", f"connect-src 'self' {api};" in csp, csp[:120])
    check("no framing", h.get("x-frame-options") == "DENY" and "frame-ancestors 'none'" in csp)
    check("nosniff", h.get("x-content-type-options") == "nosniff")
    check("config.js points at the API", api in c.get(f"{site}/config.js").text)


if __name__ == "__main__":
    api, site = sys.argv[1].rstrip("/"), (sys.argv[2].rstrip("/") if len(sys.argv) > 2 else None)
    print("API", api)
    api_checks(api, site)
    if site:
        print("site", site)
        site_checks(site, api)
    print(f"\n{len(failures)} failed" + (": " + "; ".join(failures) if failures else ""))
    sys.exit(1 if failures else 0)
