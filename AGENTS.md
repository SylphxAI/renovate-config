# renovate-config — local agent notes only

Static engineering and delivery standards load from the active Skills runtime
([SylphxAI/skills](https://github.com/SylphxAI/skills) is binding instruction
SSOT). Doctrine and Mission Control are retired historical lineage and must not
be loaded as current instruction authority.

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
