from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "sentry"
CLI = PLUGIN_ROOT / "bin" / "sentry-remediation"


def issue(short_id: str, numeric_id: int, last_seen: str, *, status: str = "unresolved") -> dict:
    return {
        "id": str(numeric_id),
        "shortId": short_id,
        "title": f"Issue {short_id}",
        "firstSeen": last_seen,
        "lastSeen": last_seen,
        "status": status,
        "substatus": "ongoing",
        "count": "1",
        "permalink": f"https://example.sentry.io/issues/{numeric_id}/",
        "project": {"id": "42", "name": "example", "slug": "example", "platform": "python"},
    }


class SentryRemediationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fixture = self.root / "issues.json"
        self.calls = self.root / "calls.jsonl"
        self.fake_sentry = self.root / "sentry"
        self.fake_sentry.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json, os, sys
                from pathlib import Path
                args = sys.argv[1:]
                with Path(os.environ["SENTRY_CALLS"]).open("a") as handle:
                    handle.write(json.dumps(args) + "\\n")
                if args[:2] == ["cli", "defaults"]:
                    print(json.dumps({"defaults": {"organization": "example", "project": None}}))
                elif args[:2] == ["issue", "list"]:
                    values = json.loads(Path(os.environ["SENTRY_FIXTURE"]).read_text())
                    limit = int(args[args.index("--limit") + 1])
                    cursor = int(args[args.index("--cursor") + 1]) if "--cursor" in args else 0
                    page = values[cursor:cursor + limit]
                    end = cursor + len(page)
                    print(json.dumps({"data": page, "hasMore": end < len(values), "nextCursor": str(end) if end < len(values) else None}))
                else:
                    print("unexpected", file=sys.stderr)
                    raise SystemExit(64)
                """
            ),
            encoding="utf-8",
        )
        self.fake_sentry.chmod(0o755)
        self.write_issues([])

    def tearDown(self):
        self.temp.cleanup()

    def write_issues(self, values):
        self.fixture.write_text(json.dumps(values), encoding="utf-8")

    def run_cli(self, *args, expected=0, page_size=None):
        command = [
            str(CLI), "--sentry-bin", str(self.fake_sentry), "--target", "example/",
        ]
        if page_size:
            command.extend(["scan", "--page-size", str(page_size), *args])
        else:
            command.extend(["scan", *args])
        completed = subprocess.run(
            command,
            env={**os.environ, "SENTRY_FIXTURE": str(self.fixture), "SENTRY_CALLS": str(self.calls)},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(expected, completed.returncode, completed.stderr)
        return json.loads(completed.stdout if expected == 0 else completed.stderr)

    def test_omitted_start_defaults_to_previous_24_hours_of_last_seen(self):
        self.write_issues([
            issue("EXAMPLE-IN", 1, "2026-08-11T12:00:00Z"),
            issue("EXAMPLE-OLD", 2, "2026-08-11T11:59:59Z"),
            issue("EXAMPLE-END", 3, "2026-08-12T12:00:00Z"),
        ])
        result = self.run_cli("--until", "2026-08-12T12:00:00Z")
        self.assertEqual(["EXAMPLE-IN"], [item["issue"]["short_id"] for item in result["candidates"]])
        self.assertEqual("lastSeen", result["window"]["field"])
        self.assertTrue(result["window"]["defaulted_to_previous_24_hours"])

    def test_relative_and_absolute_windows_are_equivalent(self):
        self.write_issues([
            issue("EXAMPLE-RECENT", 1, "2026-08-12T10:30:00Z"),
            issue("EXAMPLE-OLDER", 2, "2026-08-12T09:30:00Z"),
        ])
        relative = self.run_cli("--since", "2h", "--until", "2026-08-12T12:00:00Z")
        absolute = self.run_cli(
            "--since", "2026-08-12T10:00:00Z", "--until", "2026-08-12T12:00:00Z"
        )
        self.assertEqual(relative["candidates"], absolute["candidates"])
        self.assertFalse(relative["window"]["defaulted_to_previous_24_hours"])

    def test_same_window_is_repeatable_without_checkpoint_state(self):
        self.write_issues([issue("EXAMPLE-SAME", 4, "2026-08-12T11:00:00Z")])
        arguments = ("--since", "24h", "--until", "2026-08-12T12:00:00Z")
        first = self.run_cli(*arguments)
        second = self.run_cli(*arguments)
        self.assertEqual(first, second)
        self.assertEqual("event_in_window", first["candidates"][0]["reason"])
        self.assertTrue(first["stateless"])
        self.assertEqual([], list(self.root.glob("*state*")))

    def test_paginates_and_filters_each_issue_exactly(self):
        self.write_issues([
            issue("EXAMPLE-A", 1, "2026-08-12T10:00:00Z"),
            issue("EXAMPLE-B", 2, "2026-08-12T11:00:00Z"),
        ])
        result = self.run_cli("--until", "2026-08-12T12:00:00Z", page_size=1)
        self.assertEqual(2, result["count"])
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        issue_calls = [call for call in calls if call[:2] == ["issue", "list"]]
        self.assertEqual(2, len(issue_calls))
        self.assertTrue(all("--period" in call for call in issue_calls))

    def test_missing_last_seen_is_not_treated_as_unbounded_evidence(self):
        value = issue("EXAMPLE-MISSING", 5, "2026-08-12T11:00:00Z")
        value["lastSeen"] = None
        self.write_issues([value])
        result = self.run_cli("--until", "2026-08-12T12:00:00Z")
        self.assertEqual([], result["candidates"])
        self.assertEqual(1, result["skipped_without_last_seen"])

    def test_invalid_or_reversed_windows_fail_closed(self):
        missing_zone = self.run_cli("--since", "2026-08-12T10:00:00", expected=1)
        reversed_window = self.run_cli(
            "--since", "2026-08-13T00:00:00Z", "--until", "2026-08-12T00:00:00Z", expected=1
        )
        self.assertEqual("invalid_window", missing_zone["error"]["code"])
        self.assertEqual("invalid_window", reversed_window["error"]["code"])


if __name__ == "__main__":
    unittest.main()
