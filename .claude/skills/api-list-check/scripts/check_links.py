#!/usr/bin/env python3
"""Prüft alle URLs in api_list.json und schreibt das Ergebnis als JSON.

Nur Standardbibliothek. Verändert api_list.json nicht.

Aufruf (aus dem Projektroot):
    python3 .claude/skills/api-list-check/scripts/check_links.py --out ergebnis.json
"""
import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from urllib.parse import urljoin, urlsplit

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 api-list-check/1.0")
TIMEOUT = 30
MAX_HOPS = 8
HOST_DELAY = 1.0  # Sekunden Mindestabstand pro Host
REQUIRED_KEYS = ["name", "url", "description", "license", "contentFormats",
                 "limitations", "documentation", "howToRequestAccess",
                 "lastSighted", "lastModified"]

URL_RE = re.compile(r'https?://[^\s|)\]"<>]+')


# ── URLs einsammeln ─────────────────────────────────────────────────────────

def urls_in(text):
    return [u.rstrip(".,;") for u in URL_RE.findall(text or "")]


def collect(entry):
    """Liefert [(feld, url)] für einen Eintrag."""
    found = []
    if entry.get("url"):
        found.append(("url", entry["url"]))
    for u in urls_in(entry.get("endpoint")):
        found.append(("endpoint", u))
    for i, doc in enumerate(entry.get("documentation") or []):
        if doc.get("url"):
            found.append((f"documentation[{i}]", doc["url"]))
    access = entry.get("howToRequestAccess") or {}
    for lang in ("en", "de"):
        for u in urls_in(access.get(lang)):
            found.append(("howToRequestAccess", u))
    seen, unique = set(), []
    for field, u in found:
        if (field, u) not in seen:
            seen.add((field, u))
            unique.append((field, u))
    return unique


# ── HTTP ────────────────────────────────────────────────────────────────────

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)
_host_locks = {}
_host_last = {}
_guard = threading.Lock()


def _throttle(host):
    with _guard:
        lock = _host_locks.setdefault(host, threading.Lock())
    with lock:
        wait = HOST_DELAY - (time.time() - _host_last.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        _host_last[host] = time.time()


def _get_once(url):
    """Ein GET ohne Redirect-Folgen. Rückgabe: (status, location, fehler)."""
    parts = urlsplit(url)
    _throttle(parts.netloc)
    request_url = url.split("#", 1)[0]
    req = urllib.request.Request(request_url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/json,application/xml;q=0.9,*/*;q=0.8",
    })
    try:
        with _opener.open(req, timeout=TIMEOUT) as r:
            return r.status, None, None
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location"), None
    except Exception as e:  # DNS, TLS, Timeout, ...
        return None, None, f"{type(e).__name__}: {e}"


def fetch(url):
    """Folgt Redirects manuell und merkt sich die Kette."""
    chain, current = [], url
    for _ in range(MAX_HOPS + 1):
        status, location, error = _get_once(current)
        if error or (status and (status == 429 or status >= 500)):
            time.sleep(3)  # ein Wiederholungsversuch
            status, location, error = _get_once(current)
        if error:
            return chain, None, error
        chain.append({"status": status, "url": current})
        if status in (301, 302, 303, 307, 308) and location:
            nxt = urljoin(current, location)
            if "#" in url and "#" not in nxt:
                nxt += "#" + url.split("#", 1)[1]
            current = nxt
            continue
        return chain, status, None
    return chain, None, "Zu viele Weiterleitungen"


# ── Bewertung ───────────────────────────────────────────────────────────────

def _host(u):
    h = urlsplit(u).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _norm(u):
    p = urlsplit(u)
    return (_host(u), p.path.rstrip("/"), p.query)


def classify(fields, orig, chain, status, error):
    """Gibt (kind, auto_fix, proposed_url) zurück."""
    if error:
        return "unreachable", False, None
    final = chain[-1]["url"]
    hops = [c["status"] for c in chain[:-1]]
    only_endpoint = all(f == "endpoint" for f in fields)

    if 200 <= status < 300:
        if not hops:
            return "ok", False, None
        permanent = all(s in (301, 308) for s in hops)
        same_site = _host(orig) == _host(final)
        orig_path = urlsplit(orig).path
        final_path = urlsplit(final).path
        loses_path = final_path in ("", "/") and orig_path not in ("", "/")
        cosmetic = _norm(orig) == _norm(final)
        # Endpoint-Basis-URLs landen in fremdem Code: nur rein kosmetische
        # Änderungen (http→https, www, Schrägstrich) kommen überhaupt in Frage.
        safe = permanent and same_site and not loses_path
        if "endpoint" in fields:
            safe = safe and cosmetic
        if safe:
            if "endpoint" in fields:
                # Die Doku nennt den Endpoint oft genau in der alten Schreibweise;
                # die Entscheidung fällt erst nach dem Inhaltsvergleich.
                return "redirect_endpoint_cosmetic", False, final
            return "redirect_safe", True, final
        return "redirect_review", False, final

    if status in (401, 403, 429):
        return "blocked", False, None
    # Basis-URLs von APIs liefern ohne Pfad/Parameter oft 400, 404 oder 405,
    # obwohl der Dienst läuft – das ist kein Linkfehler.
    if status in (400, 404, 405, 415, 422) and only_endpoint:
        return "endpoint_needs_params", False, None
    if status in (404, 410):
        return "dead", False, None
    if 400 <= status < 500:
        return "client_error", False, None
    if status >= 500:
        return "server_error", False, None
    return "other", False, None


# ── Datenprüfungen (ohne Netz) ──────────────────────────────────────────────

def data_checks(entries, today, base_dir):
    issues = []
    for e in entries:
        name = e.get("name", "?")
        for k in REQUIRED_KEYS:
            if k not in e:
                issues.append({"entry": name, "issue": f"Feld '{k}' fehlt"})
        s = e.get("lastSighted")
        if not s:
            issues.append({"entry": name, "issue": "lastSighted ist leer"})
        else:
            try:
                d = datetime.strptime(s, "%Y-%m-%d").date()
                age = (today - d).days
                if age < 0:
                    issues.append({"entry": name, "issue": f"lastSighted liegt in der Zukunft ({s})"})
                elif age > 400:
                    issues.append({"entry": name, "issue": f"lastSighted ist {age} Tage alt ({s}) – Tippfehler oder lange nicht geprüft"})
            except ValueError:
                issues.append({"entry": name, "issue": f"lastSighted hat ungültiges Format ({s})"})
        demo = e.get("demo")
        if demo and not os.path.exists(os.path.join(base_dir, demo)):
            issues.append({"entry": name, "issue": f"demo-Datei nicht gefunden: {demo}"})
    return issues


# ── main ────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", default="api_list.json")
    ap.add_argument("--out", required=True, help="Pfad der Ergebnis-JSON")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    with open(args.list, encoding="utf-8") as f:
        entries = json.load(f)

    usage = {}  # url -> [{entry, field}]
    for e in entries:
        for field, u in collect(e):
            usage.setdefault(u, []).append({"entry": e["name"], "field": field})

    checkable = [u for u in usage if "{" not in u]
    print(f"{len(entries)} Einträge, {len(usage)} eindeutige URLs "
          f"({len(usage) - len(checkable)} Vorlagen übersprungen)", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        fetched = dict(zip(checkable, pool.map(fetch, checkable)))

    results = []
    for u, uses in usage.items():
        fields = [x["field"] for x in uses]
        if u not in fetched:
            results.append({"url": u, "used_in": uses, "kind": "template",
                            "status": None, "chain": [], "auto_fix": False,
                            "proposed_url": None, "error": None})
            continue
        chain, status, error = fetched[u]
        kind, auto, proposed = classify(fields, u, chain, status, error)
        results.append({"url": u, "used_in": uses, "kind": kind,
                        "status": status, "chain": chain, "auto_fix": auto,
                        "proposed_url": proposed, "error": error})

    summary = {}
    for r in results:
        summary[r["kind"]] = summary.get(r["kind"], 0) + 1

    today = date.today()
    out = {
        "checked_at": today.isoformat(),
        "summary": summary,
        "results": sorted(results, key=lambda r: (r["kind"] == "ok", r["kind"])),
        "data_checks": data_checks(entries, today, os.path.dirname(os.path.abspath(args.list))),
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False))
    print(f"Ergebnis: {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
