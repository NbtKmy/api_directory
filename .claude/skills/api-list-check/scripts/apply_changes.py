#!/usr/bin/env python3
"""Wendet sichere Änderungen auf api_list.json an.

Plan-Datei (JSON):
{
  "date": "2026-11-02",                      # optional, Standard: heute
  "url_replacements": [{"old": "...", "new": "..."}],
  "sighted": ["ArXiv", "OpenAlex"]           # Einträge, deren lastSighted gesetzt wird
}

URLs werden nur ersetzt, wenn sie vollständig dastehen (nicht als Anfang einer
längeren URL). Format der Datei bleibt erhalten (indent=2, UTF-8, Zeilenende).

Aufruf:
    python3 .claude/skills/api-list-check/scripts/apply_changes.py --plan plan.json [--dry-run]
"""
import argparse
import json
import re
import sys
from datetime import date


def replace_in(value, pattern, new, counter):
    if isinstance(value, str):
        result, n = pattern.subn(lambda _m: new, value)
        counter[0] += n
        return result
    if isinstance(value, list):
        return [replace_in(v, pattern, new, counter) for v in value]
    if isinstance(value, dict):
        return {k: replace_in(v, pattern, new, counter) for k, v in value.items()}
    return value


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--list", default="api_list.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(args.plan, encoding="utf-8") as f:
        plan = json.load(f)
    with open(args.list, encoding="utf-8") as f:
        data = json.load(f)

    for rep in plan.get("url_replacements", []):
        pattern = re.compile(r"(?<![\w/.\-])" + re.escape(rep["old"]) + r"(?=[\s\"')|\]]|$)")
        counter = [0]
        data = replace_in(data, pattern, rep["new"], counter)
        print(f"{counter[0]}× ersetzt: {rep['old']} -> {rep['new']}")
        if counter[0] == 0:
            print(f"  WARNUNG: {rep['old']} nicht gefunden", file=sys.stderr)

    day = plan.get("date") or date.today().isoformat()
    names = {e["name"]: e for e in data}
    for name in plan.get("sighted", []):
        if name not in names:
            sys.exit(f"Eintrag nicht gefunden: {name}")
        names[name]["lastSighted"] = day
    if plan.get("sighted"):
        print(f"lastSighted = {day} für {len(plan['sighted'])} Einträge")

    if args.dry_run:
        print("Dry-Run: nichts geschrieben")
        return
    with open(args.list, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
