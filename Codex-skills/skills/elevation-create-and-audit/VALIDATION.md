# Working elevation skill validation

## Effective Version 5 update — 2026-10-16

The source-owned simplification procedure and owner's factory-review presentation profile were added after the A200 r03 correction exercise. Fresh checks in `Vancouver Wood Carving/skill-packages/staging/effective-version-5-work/` validate structure/local links, four update-helper tests, companion decision cases, actual export geometry and 39 detectable drawing defects. The A200 artifact manifest and independently generated build hashes were rechecked; 125 recorded files and 206 historical-anchor files were unchanged. Detail crops for dimension clearance, curved silhouettes, repaired board edges and orphan callout removal were inspected directly.

PyYAML is unavailable in the active Python runtime, so the optional skill-creator quick validator cannot run; the main skill's structure/link/lesson validator and guarded update tests pass. Temporary-directory permission and Windows path-length failures were retained in staging logs and corrected by using an isolated permitted extended-length temporary path; they are not drawing failures or new shared drawing rules.

Source fidelity remains qualified by the recorded source controls and inclusion scope. A200 r03 still awaits user review, calibrated estimates still need confirmation, and a fully constrained shared 3D solid remains pending. No new unseen-customer generalization or fabrication certification is claimed. Skill snapshotting does not change those statuses. Earlier validation below is historical evidence, not a new test of those drawings.

Status: candidate update validated from the Kitchen 4, 3, and 1 correction exercises, including the cross-view stepped-base and wall-base correction. The frozen Effective Skill 2 restoration point remains unchanged.

## Instruction-level validation passed

- Skill frontmatter and all local reference links validated.
- Existing Effective Skill 2 decision regressions remain applicable for evidence-backed dividers, dimensioned context, complete contours, bound measurements, redundant inference, and contradictory source chains.
- Kitchen 4, 3, and 1 exported-geometry mutations passed for dimension clearance, wall continuity, explicit toe kicks, cross-view height consistency, door-symbol ownership and direction, drawer marks, source dimensions, and slat coverage.
- The later base-detail correction passed exact endpoint, stepped-contour, unchanged-neighbor, wall-base-junction, visual PDF, and two-build repeatability checks. Its normal validator now detects 20 mutations: the earlier model/layout faults plus five export-only defects with the correct canonical model unchanged (flattened step, shortened edge, shifted junction, blue edge, and dashed edge).
- Source review is now a separate evidence-and-hash-bound record. A visual-status flag cannot set it, and a deliberately stale reviewed artifact hash is rejected.
- Add Objects and Separate Objects retain transformation-specific procedures while inheriting the main skill's evidence, dimension, presentation, export, and acceptance rules.
- Line-taxonomy regressions passed.
- Version-helper rollback, stale-writer, invalid-stage, and lock tests passed using a task-local temporary directory.
- The installed and workspace-package managed fingerprints must match after promotion. The frozen Effective Skill 2 fingerprint is intentionally different and must not change.

The optional `skill-creator` quick validator was unavailable because PyYAML is not installed in that helper runtime. The skill's own structure and link validator passed and is the controlling validation for this package.

## Drawing evidence boundary

The Kitchen 4, 3, and 1 candidate supplied reviewed correction evidence. The source-supported short residual resolved the previously recorded local Kitchen 3 chain discrepancy for this experiment, but its numeric value remains project-specific. The reusable rules concern endpoint correspondence, stepped contour modeling, wall-base separation, and validation behavior—not project dimensions. This working skill is not claimed to be proven on unseen customer drawings.

The earlier project-scoped `Effective Version 1` drawing anchor remains frozen and unchanged. Its relationship to the user's remembered “Effective Skill 1” is unverified.
