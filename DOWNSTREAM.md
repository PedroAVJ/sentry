# Downstream provenance

This repository maintains a downstream integration of [Sentry](https://github.com/getsentry/plugin-codex).

- Upstream baseline at conversion: `v1.3.2` / `1f076eb`.
- Upstream source: `https://github.com/getsentry/plugin-codex.git`.
- Component: `plugins/sentry` in the upstream source.
- Public release history starts from an audited source snapshot. Historical
  private conversion branches, tags, and merge parents must not be republished.
- Upstream copyright and license notices remain intact. See
  `LICENSE` and `THIRD_PARTY_NOTICES.md` for license evidence.

## Updating the downstream

Fetch the official upstream into an isolated task clone. Compare the exact
component against the recorded baseline, preserve its attribution, and apply
only reviewed changes to this repository. Keep downstream additions visibly
separate from vendor code. Recheck upstream license declarations for new files.
Do not merge or push an archived private branch as part of an upstream update.

Run the repository tests and plugin validators before publishing. Source,
client installation, and live account behavior are separate verification steps.
