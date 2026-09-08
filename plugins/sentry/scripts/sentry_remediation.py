#!/usr/bin/env python3
"""Read a stateless, source-event-time-bounded Sentry issue window."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Any, Mapping, Optional, Sequence


DEFAULT_WINDOW = dt.timedelta(hours=24)
DEFAULT_PAGE_SIZE = 1000
_DURATION = re.compile(r"^(?P<amount>\d+(?:\.\d+)?)(?P<unit>[mhdw])$")


class SentryRemediationError(RuntimeError):
    def __init__(self, code: str, message: str, details: Optional[Mapping[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


def emit(value: Mapping[str, Any], stream: Any = sys.stdout) -> None:
    json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
    stream.write("\n")


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _absolute_time(value: str, option: str) -> dt.datetime:
    raw = value.strip()
    try:
        parsed = dt.datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError as exc:
        raise SentryRemediationError("invalid_window", f"{option} must be an ISO-8601 timestamp with a timezone.") from exc
    if parsed.tzinfo is None:
        raise SentryRemediationError("invalid_window", f"{option} must include a timezone.")
    return parsed.astimezone(dt.timezone.utc)


def _duration(value: str) -> Optional[dt.timedelta]:
    match = _DURATION.fullmatch(value.strip().casefold())
    if not match:
        return None
    amount = float(match.group("amount"))
    seconds = amount * {"m": 60, "h": 3600, "d": 86400, "w": 604800}[match.group("unit")]
    if seconds <= 0:
        return None
    return dt.timedelta(seconds=seconds)


def resolve_window(
    since: Optional[str],
    until: Optional[str],
    *,
    now: Optional[dt.datetime] = None,
) -> tuple[dt.datetime, dt.datetime, bool]:
    end = _absolute_time(until, "--until") if until else (now or dt.datetime.now(dt.timezone.utc))
    end = end.astimezone(dt.timezone.utc)
    defaulted = since is None
    if since is None:
        start = end - DEFAULT_WINDOW
    else:
        relative = _duration(since)
        start = end - relative if relative else _absolute_time(since, "--since")
    if start >= end:
        raise SentryRemediationError("invalid_window", "--since must be earlier than --until.")
    return start, end, defaulted


def binary(raw: Optional[str]) -> str:
    return raw or os.environ.get("SENTRY_REMEDIATION_BIN") or "sentry"


def run_process(executable: str, *args: str) -> str:
    resolved = shutil.which(executable) if "/" not in executable else executable
    if not resolved:
        raise SentryRemediationError("sentry_cli_missing", "The Sentry CLI was not found.", {"binary": executable})
    try:
        completed = subprocess.run(
            [resolved, *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        raise SentryRemediationError("sentry_cli_timeout", "The Sentry issue scan timed out.") from exc
    if completed.returncode != 0:
        raise SentryRemediationError(
            "sentry_cli_failed",
            "The Sentry CLI could not read issue groups.",
            {"exit_code": completed.returncode, "stderr": completed.stderr.strip()[-2000:]},
        )
    return completed.stdout


def parse_json_output(raw: str, command: str) -> Mapping[str, Any]:
    decoder = json.JSONDecoder()
    for index, character in enumerate(raw):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise SentryRemediationError("invalid_sentry_json", "The Sentry CLI returned invalid JSON.", {"command": command})


def resolve_target(executable: str, raw: Optional[str]) -> str:
    target = raw or os.environ.get("SENTRY_REMEDIATION_TARGET")
    if target:
        return target
    envelope = parse_json_output(run_process(executable, "cli", "defaults", "--json"), "sentry cli defaults")
    defaults = envelope.get("defaults")
    if not isinstance(defaults, dict) or not isinstance(defaults.get("organization"), str):
        raise SentryRemediationError("sentry_target_missing", "Configure a Sentry organization or pass --target.")
    project = defaults.get("project")
    return f"{defaults['organization']}/{project or ''}"


def normalize_issue(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SentryRemediationError("invalid_sentry_issue", "A Sentry issue was not an object.")
    for key in ("id", "shortId"):
        if not isinstance(raw.get(key), str) or not raw[key]:
            raise SentryRemediationError("invalid_sentry_issue", f"A Sentry issue omitted {key}.")
    project = raw.get("project") if isinstance(raw.get("project"), dict) else {}
    return {
        "id": raw["id"],
        "short_id": raw["shortId"],
        "title": raw.get("title") if isinstance(raw.get("title"), str) else "",
        "status": raw.get("status") if isinstance(raw.get("status"), str) else "",
        "substatus": raw.get("substatus") if isinstance(raw.get("substatus"), str) else "",
        "first_seen": raw.get("firstSeen") if isinstance(raw.get("firstSeen"), str) else "",
        "last_seen": raw.get("lastSeen") if isinstance(raw.get("lastSeen"), str) else "",
        "count": str(raw.get("count", "")),
        "permalink": raw.get("permalink") if isinstance(raw.get("permalink"), str) else "",
        "project": {
            key: project.get(key)
            for key in ("id", "name", "slug", "platform")
            if isinstance(project.get(key), str)
        },
    }


def _fetch_period(start: dt.datetime, end: dt.datetime) -> str:
    # issue list accepts day-granular ranges. Widen the retrieval by a day and
    # enforce the exact half-open lastSeen interval locally.
    first = start.astimezone(dt.timezone.utc).date()
    last = end.astimezone(dt.timezone.utc).date() + dt.timedelta(days=1)
    return f"{first.isoformat()}..{last.isoformat()}"


def fetch_issues(
    executable: str,
    target: str,
    query: str,
    start: dt.datetime,
    end: dt.datetime,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    if not 1 <= page_size <= 1000:
        raise SentryRemediationError("invalid_page_size", "--page-size must be between 1 and 1000.")
    cursor: Optional[str] = None
    seen_cursors: set[str] = set()
    issues: dict[str, dict[str, Any]] = {}
    missing_last_seen = 0
    while True:
        arguments = [
            "issue", "list", target,
            "--period", _fetch_period(start, end),
            "--limit", str(page_size),
            "--sort", "new",
            "--fresh",
            "--json",
        ]
        if query:
            arguments.extend(["--query", query])
        if cursor:
            arguments.extend(["--cursor", cursor])
        envelope = parse_json_output(run_process(executable, *arguments), "sentry issue list")
        data = envelope.get("data")
        if not isinstance(data, list):
            raise SentryRemediationError("invalid_sentry_json", "Sentry issue JSON omitted its data array.")
        for raw in data:
            issue = normalize_issue(raw)
            if not issue["last_seen"]:
                missing_last_seen += 1
                continue
            try:
                last_seen = _absolute_time(issue["last_seen"], "lastSeen")
            except SentryRemediationError as exc:
                raise SentryRemediationError(
                    "invalid_sentry_issue",
                    f"Sentry issue {issue['short_id']} has an invalid lastSeen timestamp.",
                ) from exc
            if not start <= last_seen < end:
                continue
            existing = issues.get(issue["short_id"])
            if existing and existing["id"] != issue["id"]:
                raise SentryRemediationError("issue_identity_collision", "A Sentry short ID resolved to multiple IDs.")
            issues[issue["short_id"]] = issue
        if envelope.get("hasMore") is not True:
            break
        next_cursor = envelope.get("nextCursor")
        if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
            raise SentryRemediationError("invalid_sentry_pagination", "Sentry returned an invalid pagination cursor.")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    return sorted(issues.values(), key=lambda item: (item["last_seen"], item["short_id"])), missing_last_seen


def scan(args: argparse.Namespace) -> Mapping[str, Any]:
    start, end, defaulted = resolve_window(args.since, args.until)
    executable = binary(args.sentry_bin)
    target = resolve_target(executable, args.target)
    issues, missing_last_seen = fetch_issues(
        executable, target, args.query or "", start, end, args.page_size
    )
    candidates = [{"reason": "event_in_window", "issue": issue} for issue in issues]
    return {
        "source": "sentry",
        "target": target,
        "query": args.query or "",
        "window": {
            "field": "lastSeen",
            "since": _iso(start),
            "until": _iso(end),
            "bounds": "[since, until)",
            "defaulted_to_previous_24_hours": defaulted,
        },
        "count": len(candidates),
        "candidates": candidates,
        "skipped_without_last_seen": missing_last_seen,
        "stateless": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read Sentry issue groups active in a bounded event-time window.")
    parser.add_argument("--sentry-bin")
    parser.add_argument("--target")
    parser.add_argument("--query", default="")
    commands = parser.add_subparsers(dest="command", required=True)
    scan_parser = commands.add_parser("scan", help="read issue groups whose last event falls in a window")
    scan_parser.add_argument(
        "--since",
        help="ISO-8601 start time, or a duration such as 24h relative to --until/current time",
    )
    scan_parser.add_argument("--until", help="ISO-8601 exclusive end time; defaults to now")
    scan_parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        emit(scan(args))
        return 0
    except SentryRemediationError as exc:
        emit(
            {"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
            stream=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
