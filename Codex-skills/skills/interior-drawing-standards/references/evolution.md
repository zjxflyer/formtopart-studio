# Verified learning procedure

Learning runs only during an active task and only within this skill and its learning records. Current user instructions and filesystem permissions still govern writes.

Classify lessons as:

- `project`: customer-specific symbols, meanings, orientations, editions, dimensions, and facts; store only in the project;
- `interpretation`: broadly supported symbol or applicability guidance with citations and limitations;
- `preference`: an explicit reusable owner presentation preference.

Unverified or conflicting lessons remain candidates. A shared lesson record includes id, scope, observation, cause, proposed rule, citations/evidence, limitations, verification statuses, behavioral/visual flags, basis, and status.

Before adoption, re-check cited sources and the actual correction. Behavioral changes require relevant regression checks. Visual changes require rendered inspection. All changes require instruction review for scope, conflicts, weakened checks, accidental project constants, and overstated authority.

Prepare updates in a separate staging copy, fingerprint the installed skill immediately before editing, and use the version helper:

```text
python scripts/skill_versions.py fingerprint --root SKILL_DIRECTORY
python scripts/skill_versions.py validate --root STAGED_DIRECTORY
python scripts/skill_versions.py apply --root SKILL_DIRECTORY --staged STAGED_DIRECTORY --expected FINGERPRINT --lesson LESSON_JSON
python scripts/skill_versions.py rollback --root SKILL_DIRECTORY --version VERSION_ID --expected CURRENT_FINGERPRINT
```

The helper rejects stale fingerprints and project facts, snapshots managed files, validates the staged skill, preserves adopted evidence, and restores prior files if installation fails. Do not remove a concurrent-update lock without inspecting it.

Report adopted lesson IDs, validation status, and remaining candidates. Do not update `$elevation-create-and-audit`, unrelated skills, Codex settings, or memory as a side effect; coordinate a separate verified update when a reconstruction lesson belongs there.
