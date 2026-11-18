---
name: interior-drawing-standards
description: Interpret customer plan, elevation, section, symbol, and mixed-material conventions using cited Canadian and Vancouver references. Use for standards checks or uncertain drawing meanings; do not use it to invent geometry or silently redesign customer drawings.
---

# Interior drawing standards

Interpret drawing language and applicable requirements while preserving the customer's design intent. Vancouver is the default jurisdiction when the project location is not otherwise stated. This skill advises; it does not certify compliance or replace a qualified architect, engineer, code consultant, fabricator, or authority having jurisdiction.

## Route the question

- For authority, edition, jurisdiction, and applicability, read [authority-and-applicability.md](references/authority-and-applicability.md).
- For plans, elevations, sections, symbols, line types, and confidence handling, read [drawing-language.md](references/drawing-language.md).
- For wood, stone/tile, glass/mirror, metal, coatings, lighting, and other materials, read [material-systems.md](references/material-systems.md).
- For maintained citations and access limits, read [reference-index.md](references/reference-index.md).
- For the response schema and worked cases, read [interpretation-records.md](references/interpretation-records.md).
- Before claiming validation, read [validation.md](references/validation.md).
- After a reusable, verified correction, read [evolution.md](references/evolution.md).

## Interpretation contract

Use evidence in this order:

1. contract documents, addenda, explicit customer legends, notes, and schedules;
2. corroborating plans, elevations, sections, details, and repeated use in the same set;
3. mandatory requirements that actually apply to the project, edition, location, occupancy, and scope;
4. project-specified standards and industry guidance;
5. software conventions and general drafting custom.

External conventions can explain an unresolved mark or flag a possible issue. They cannot override clear project evidence, silently replace customer symbols, or create a seam, component, material region, dimension, or operation.

Return possible interpretations, evidence, source class, applicability, confidence, alternatives, confirmation needs, and separate compliance-review flags. Keep `appearance_confidence` separate from `meaning_confidence`. A source symbol may be reproduced accurately even when its meaning is unresolved.

Distinguish these source classes: mandatory law or regulation; contractual/project requirement; incorporated or specified standard; industry guidance; software convention; customer-specific notation; project inference. A publication being newer does not make it applicable. Record edition, jurisdiction, access limitations, and verification date.

Use `$elevation-create-and-audit` to reconstruct or revise drawings. That skill owns geometry, dimensions, rendering, and independent audit. This skill must not mutate a drawing as a side effect of interpretation.

## Active, verified learning

Learning occurs only during an active task. Store customer-specific symbols in the project. Add broadly supported interpretation guidance here only with citations and limitations. Keep unresolved or conflicting lessons as candidates. Adopt a behavioral change only after relevant regression checks; adopt a visual convention only after rendered inspection. Snapshot prior versions, reject concurrent edits, retain rollback capability, and report adopted lesson IDs.
