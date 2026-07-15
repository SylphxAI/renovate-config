# renovate-config — local agent notes only

Doctrine and fleet delivery law live in the **host always-on constitution**
(`~/.grok/AGENTS.md` / Doctrine template). This file must **not** restate,
weaken, or fork that law (including PR-vs-direct-trunk delivery).

Local truth: `PROJECT.md`, `.doctrine/project.json` when present.

## Boundary hazards

- Keep this repository generic. Project-specific dependency policy belongs in
- Treat `default.json` as the public contract for all repositories extending
- Do not enable broad automerge, schedule, or grouping changes without evidence
- Do not encode secrets, private registry credentials, or repo-specific tokens.

## Local commands

- JSON parse validation for `default.json`
- diff review against README behavior
- central project manifest audit
- Prefer the **narrowest** affected check before full workspace runs.
- Report layers honestly: local diff · trunk FF · deploy · prod proof (do not collapse).

## Validation notes

- Prefer the **narrowest** affected check before full workspace runs.
- Report layers honestly: local diff · trunk FF · deploy · prod proof (do not collapse).
