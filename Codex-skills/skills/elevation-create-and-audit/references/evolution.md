# Verified learning procedure

## Superseded interpretations

Review later customer corrections before adopting an earlier lesson with passed flags. Preserve original evidence and record supersession, reason, and successor in an external project index rather than rewriting frozen artifacts. Adopt the reusable decision rule separately from any disputed project interpretation. A blocked drawing may support a narrow workflow lesson without certifying that drawing.

Instruction-only changes can be evaluated through isolated decision cases; document that scope and do not claim a new rendered visual review. Use explicit-user-preference basis for an owner-requested workflow when appropriate. Keep unverified geometry or mechanism claims as candidates. Future review records must identify artifact hashes so regenerated evidence cannot inherit approval.


Learning runs only during an active use. This owner authorized verified automatic updates; current user instructions and filesystem permissions still govern every write. For installation or updates outside writable roots, use the normal approval mechanism; do not bypass it.

At a meaningful correction, record a JSON lesson with: id, scope (invariant, preference, project), observation, cause, proposed_rule, evidence (nonempty list of source/artifact references), verification (regression, visual, instruction_review statuses: passed/pending/failed/not-applicable), behavioral_change, visual_change, basis (verified-correction or explicit-user-preference), and status (candidate or adopted).

Store project lessons in the project, not in this shared skill. Candidate shared lessons belong in learning/candidates; adopted records go in learning/records. Use evidence references and concise descriptions rather than copying private source drawings. Seed lessons are historical and must not be represented as newly tested behavior.

Before adoption, inspect the actual evidence. A verified correction needs regression=passed when behavioral_change is true, and visual=passed when visual_change is true. An explicit user preference may establish a rule without proving a prior implementation correct. All adoption requires instruction_review=passed: inspect the proposed diff for user-intent conflicts, weakened checks, excess scope, and accidental project constants. Script checks validate records, not truthfulness or semantic safety.

Prepare changes in a staging copy. Run the skill creator's quick_validate.py when available and check local links. Use:

```text
python scripts/skill_versions.py fingerprint --root SKILL_DIRECTORY
python scripts/skill_versions.py validate --root STAGED_DIRECTORY
python scripts/skill_versions.py apply --root SKILL_DIRECTORY --staged STAGED_DIRECTORY --expected FINGERPRINT --lesson LESSON_JSON
python scripts/skill_versions.py rollback --root SKILL_DIRECTORY --version VERSION_ID --expected CURRENT_FINGERPRINT
```

Fingerprint before editing. The helper locks updates, rejects a stale fingerprint, validates staging and lesson eligibility, snapshots the previous managed files, and preserves candidate evidence. Do not bypass a concurrent-update failure: re-read the current version and reconcile. A failed installation restores prior files; an interrupted update leaves a lock and snapshot for explicit inspection/recovery. Do not remove a lock merely because it exists.

Keep updates small. Merge duplicate lessons, preserve evidence, retire contradicted rules with reasons, and avoid growing the entrypoint into an exhaustive history. If validation fails or evidence conflicts, leave the installed rules unchanged and retain the candidate. Report adopted lesson IDs and verification with the task result. Do not update unrelated skills, settings, general memory, or drawing files as a side effect of learning.
