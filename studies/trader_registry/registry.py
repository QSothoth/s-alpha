"""Typed, validated, standard-library-only trader research registry."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date
import json
import re
from pathlib import Path
import unicodedata
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = Path(__file__).with_name("registry.json")
STATUSES = frozenset({
    "EXISTING_BASELINE_IMMUTABLE", "MAIN_EXECUTED_LIMITED_HYPOTHESES", "EXECUTED_DAILY_LIMITED_HYPOTHESES",
    "SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION", "MODEL_BLOCKED_ARCHITECTURE_TESTED",
    "EXECUTED_MINUTE_DOMAIN_DIAGNOSTIC", "EXECUTED_MINUTE_LIMITED_HYPOTHESES",
    "EXECUTED_NONTRADING_EVENT_OR_SCREEN", "EVIDENCE_OR_ACCOUNTING_ONLY",
    "REFERENCE_ONLY_NOT_IMPLEMENTED", "HISTORICAL_RESEARCH_BRANCH_ONLY",
})

EVIDENCE_GRADES = frozenset({"candidate_framework_unverified", "identity_and_results_only", "interview_framework_partial", "primary_framework_partial", "primary_rules_partial", "secondary_framework_only"})


@dataclass(frozen=True)
class Implementation:
    status: str
    code_paths: tuple[str, ...]
    report_paths: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class Trader:
    id: str
    name: str
    aliases: tuple[str, ...]
    cohort: str
    markets: tuple[str, ...]
    styles: tuple[str, ...]
    timeframes: tuple[str, ...]
    long_short_methods: tuple[str, ...]
    evidence_grade: str
    dossier_path: str
    source_ledger_paths: tuple[str, ...]
    source_urls: tuple[str, ...]
    missing_rules: tuple[str, ...]
    next_steps: tuple[str, ...]
    implementation: Implementation


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def _strings(value: object, field: str, *, nonempty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(f"{field}: expected {'nonempty ' if nonempty else ''}list")
    if any(not isinstance(v, str) or not v.strip() for v in value):
        raise ValueError(f"{field}: expected nonempty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{field}: duplicate values")
    return tuple(value)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}: expected nonempty string")
    return value


def _path(value: str, root: Path) -> None:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError(f"unsafe repository path: {value}")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise ValueError(f"missing or unsafe file: {value}")


def load_registry(path: Path = DEFAULT_PATH, *, root: Path = ROOT) -> tuple[Trader, ...]:
    """Reject malformed metadata, ambiguous aliases and dangling repository links."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"schema_version", "as_of", "traders"} or type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("unsupported registry envelope")
    date.fromisoformat(data["as_of"])
    if not isinstance(data["traders"], list) or not data["traders"]:
        raise ValueError("traders must be a nonempty list")
    result, identities = [], {}
    fields = set(Trader.__dataclass_fields__)
    list_fields = {"aliases", "markets", "styles", "timeframes", "long_short_methods", "source_ledger_paths", "source_urls", "missing_rules", "next_steps"}
    for row in data["traders"]:
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError("unexpected or missing trader fields")
        values = {k: _strings(row[k], k, nonempty=k != "aliases") if k in list_fields else _text(row[k], k) for k in fields - {"implementation"}}
        if values["cohort"] not in {"original_33", "additional_reference"}:
            raise ValueError("invalid cohort")
        if values["evidence_grade"] not in EVIDENCE_GRADES:
            raise ValueError("unknown evidence grade")
        ident = values["id"]
        if not re.fullmatch(r"[a-z][a-z0-9_]*", ident):
            raise ValueError("invalid trader id")
        impl = row["implementation"]
        if not isinstance(impl, dict) or set(impl) != set(Implementation.__dataclass_fields__):
            raise ValueError("unexpected or missing implementation fields")
        status = _text(impl["status"], "status")
        if status not in STATUSES:
            raise ValueError(f"unknown status: {status}")
        code = _strings(impl["code_paths"], "code_paths", nonempty=False)
        reports = _strings(impl["report_paths"], "report_paths", nonempty=False)
        if status.startswith("EXECUTED_") or status in {"EXISTING_BASELINE_IMMUTABLE", "MAIN_EXECUTED_LIMITED_HYPOTHESES", "MODEL_BLOCKED_ARCHITECTURE_TESTED"}:
            if not code:
                raise ValueError("implemented record requires verified code")
        if status in {"REFERENCE_ONLY_NOT_IMPLEMENTED", "HISTORICAL_RESEARCH_BRANCH_ONLY", "SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION"} and code:
            raise ValueError("unimplemented record must not advertise code")
        values["implementation"] = Implementation(status, code, reports, _text(impl["note"], "note"))
        for p in (values["dossier_path"], *values["source_ledger_paths"], *code, *reports):
            _path(p, root)
        for url in values["source_urls"]:
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"invalid source URL: {url}")
        for alias in (ident, values["name"], *values["aliases"]):
            key = normalize(alias)
            if key in identities and identities[key] != ident:
                raise ValueError(f"ambiguous identity: {alias}")
            identities[key] = ident
        if any(t.id == ident for t in result):
            raise ValueError(f"duplicate id: {ident}")
        result.append(Trader(**values))
    return tuple(result)


def query(traders: tuple[Trader, ...], text: str = "", *, status: str | None = None, cohort: str | None = None) -> tuple[Trader, ...]:
    """Case-insensitive substring search across identity and research style fields."""
    needle = normalize(text)
    return tuple(t for t in traders if (status is None or t.implementation.status == status)
                 and (cohort is None or t.cohort == cohort)
                 and needle in normalize(" ".join((t.id, t.name, *t.aliases, *t.markets, *t.styles, *t.timeframes, *t.long_short_methods))))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", nargs="?", default="")
    parser.add_argument("--status", choices=sorted(STATUSES))
    parser.add_argument("--cohort", choices=["original_33", "additional_reference"])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    rows = query(load_registry(), args.text, status=args.status, cohort=args.cohort)
    if args.json:
        print(json.dumps([asdict(t) for t in rows], ensure_ascii=False, indent=2))
    else:
        for t in rows:
            print(f"{t.id}\t{t.name}\t{'; '.join(t.styles)}\t{t.implementation.status}\t{t.dossier_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
