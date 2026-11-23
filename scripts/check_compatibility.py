#!/usr/bin/env python3
"""Check local/released frontend and backend manifests without cloning either project."""
import argparse
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen


def load(source):
    if source.startswith(("https://", "http://")):
        with urlopen(Request(source, headers={"Cache-Control": "no-cache"}), timeout=15) as response:
            return json.load(response)
    return json.loads(Path(source).read_text())


def span(value):
    low, high = value["min"], value["max"]
    if type(low) is not int or type(high) is not int or not 1 <= low <= high:
        raise ValueError("Invalid API version range")
    return low, high


def check(frontend, backend):
    if frontend.get("component") != "miniworlds-editor" or backend.get("component") != "miniworlds-editor-backend":
        raise ValueError("Wrong component manifest")
    problems = []
    for consumer, provider, key, name in [(frontend, backend, "backend_api", "Backend"), (backend, frontend, "frontend_api", "Frontend")]:
        wanted, offered = span(consumer["requires"][key]), span(provider["api"])
        if max(wanted[0], offered[0]) > min(wanted[1], offered[1]):
            action = "aktualisieren" if offered[1] < wanted[0] else "kompatible Version verwenden oder die Gegenstelle aktualisieren"
            problems.append(f"{name} {action}: benötigt API {wanted}, vorhanden {offered}")
        missing = set(consumer["requires"].get("capabilities", [])) - set(provider.get("capabilities", []))
        if missing:
            problems.append(f"{name} aktualisieren: fehlende Funktionen {', '.join(sorted(missing))}")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", required=True, help="manifest file or deployed /compatibility.json URL")
    parser.add_argument("--backend", required=True, help="manifest file or deployed /api/compatibility URL")
    args = parser.parse_args()
    try:
        frontend, backend = load(args.frontend), load(args.backend)
        problems = check(frontend, backend)
        result = {"compatible": not problems, "frontend": frontend.get("revision", frontend["version"]), "backend": backend.get("revision", backend["version"]), "actions": problems}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if problems else 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"Kompatibilität konnte nicht geprüft werden: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
