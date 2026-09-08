# Repository guidance

- This repository is the canonical downstream source for the `sentry`
  plugin. Its public upstream is `https://github.com/getsentry/plugin-codex`.
- Preserve upstream attribution and the vendor layout under `plugins/sentry`.
  Do not restore historical private refs. Keep downstream behavior in clearly named skills,
  helpers, tests, or documentation so future upstream merges remain legible.
- The upstream repository is generated from `getsentry/sentry-for-ai`. Do not
  casually rewrite vendor-generated skills; prefer adding a downstream skill
  or contributing a generally useful correction to the generating repository.
- Keep the Codex and Claude manifests synchronized. Preserve Sentry attribution
  while identifying this repository as the downstream source.
- Marketplace catalogs reference `plugins/sentry` through `git-subdir`; do not
  duplicate runtime behavior back into a marketplace repository.
- Keep credentials and personal data out of Git. Preserve stable command names,
  service labels, and credential identifiers across releases.
- Bump the plugin version for released behavior changes and run `npm test`, the
  bundled `plugin-creator/scripts/validate_plugin.py plugins/sentry` validator,
  and `claude plugin validate plugins/sentry` before publishing.
