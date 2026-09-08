# Sentry plugin downstream

This repository tracks Sentry's official
[`getsentry/plugin-codex`](https://github.com/getsentry/plugin-codex) repository
and layers PedroAVJ's operational workflows on top of the vendor plugin.

Public releases use an audited source snapshot. Upstream Sentry attribution
and licensing remain documented in this repository; private conversion history
and operator data are excluded from public release history.

## What is included

- Sentry's hosted MCP server at `https://mcp.sentry.dev/mcp`.
- Sentry's complete generated skill library for setup, instrumentation,
  debugging, alerts, releases, stack traces, OpenTelemetry, and Cocoa
  snapshots.
- A direct `sentry` CLI skill that keeps issues, events, logs, and traces
  distinct and guards against misleading environment and time-window queries.
- A bounded, stateless `remediate-issues` workflow that may prepare tested pull
  requests but never merges or deploys unattended.
- Release-qualified resolution guidance so a verified production fix retains
  issue, commit, pull-request, deployment, and regression lineage.

The plugin itself lives at `plugins/sentry`, matching the upstream repository.
Both Codex and Claude can install it from that subdirectory through the
`git-subdir` marketplace source type.

## Install

The personal `package-manager` marketplace is the canonical install source:

```bash
codex plugin marketplace upgrade package-manager
codex plugin add sentry@package-manager

claude plugin marketplace update package-manager
claude plugin install sentry@package-manager --scope user
```

The optional CLI helper is shipped inside the plugin:

```bash
plugins/sentry/bin/install-sentry-cli
```

Authenticate the hosted MCP connection through the plugin host. Authenticate
the optional CLI separately with `sentry auth login` or `SENTRY_AUTH_TOKEN`.

## Upstream maintenance

See [`DOWNSTREAM.md`](DOWNSTREAM.md) for the baseline, provenance, and update
procedure.
