---
name: elevation-create-and-audit
description: Create, correct, and audit simplified customer-confirmation plans, elevations, and sections from interior and millwork source drawings, preserving evidence-bound geometry, source symbols, readable dimensions, and verified learning from corrections.
---

# Interior drawing creation and audit

Produce source-faithful, simplified customer-confirmation plans, elevations, and sections. Default to NTS; establish separate evidence and acceptance criteria if fabrication drawings are requested. Use the user's current requirements over these defaults.

## Route the work

For multi-sheet phases, issue campaigns, full review or coordinated learning, use `$drawing-workflow` for role handoffs and project state. Keep technical source reconstruction and acceptance here.

For customer corrections, first bound the change using the correction procedure in structure.md and fresh artifact-bound acceptance in acceptance.md. Read only relevant references and targeted evidence regions; use existing runtime resolvers and managed-file staging, not repeated full evidence dumps or copies of historical snapshots. Inherited inventories and passed reports are not source evidence.

- Before reconstruction or geometry correction, read [structure.md](references/structure.md). When reusing inherited geometry, adding source overlays, or repairing clipped/missing content, also apply [source-fidelity-gates.md](references/source-fidelity-gates.md).
- Before scope filtering or simplifying a drawing, read [simplification.md](references/simplification.md): source observations, retained geometry, annotations, and omitted content are separate decisions.
- Before interpreting or redrawing customer symbols, read [source-symbols.md](references/source-symbols.md).
- For line classification and operation marks, also read [line-taxonomy.md](references/line-taxonomy.md).
- Before dimension solving or annotation changes, read [dimensions.md](references/dimensions.md). Distinguish component size from object-to-object/datum relationships; a bounding box cannot replace the latter.
- Before rendering, read [presentation.md](references/presentation.md).
- Before acceptance, read [acceptance.md](references/acceptance.md).
- For historical pitfalls, read [lessons.md](references/lessons.md). Examples teach decisions, never new-project dimensions.
- After a meaningful correction or review, read [evolution.md](references/evolution.md) and record a lesson when it adds useful evidence.

Route transformation-specific work to the companion skill instead of duplicating its procedure here: use `$drawing-add-objects` for insertion, replacement, or gap placement that can displace neighbouring assemblies; use `$drawing-separate-objects` for a standalone view extracted from an existing recursive assembly. Those skills inherit this skill's evidence, dimension, presentation, and acceptance rules.

For an explicitly requested coordinated 3D viewer, editable spatial workspace or portable read-only HTML, use `$drawing-3d-workspace`. Keep source reconstruction and static 2D acceptance here; interaction, customer-project isolation and local viewer delivery belong to that companion. Starting 3D or freezing skills does not approve the example drawings.

Use Source Evidence → Recursive Assembly Model → Solved Geometry → Annotation Layout → Outputs → Independent Audit. Maintain arbitrary recursive children rather than a fixed cabinet/part depth. Adapt existing project schemas rather than forcing a migration.

At project start, establish a symbol profile from the customer's legends, notes, plans, elevations, sections, details, and schedules. Preserve recognizable source symbols and their owning faces, but never let a symbol create a component, seam, material area, or dimension without independent structural evidence. Keep appearance confidence separate from meaning confidence.

Classify every source mark before simplifying it as `real_boundary`, `opening_operation`, `annotation`, or `texture_or_surface_detail`. Record the owner, endpoints, orientation, line pattern, evidence region, appearance confidence, meaning confidence, and retain/simplify/omit decision. Solid physical edges and confirmed seams remain geometry. Component-owned dashed marks describe an operation only when the source supports that interpretation. Decorative grain, speckle, hatch, and lighting texture may be omitted from the simplified output. A colorful or 3D reference may confirm identity, operation, or material relationships, but it cannot create an unsupported boundary or dimension.

Use `$interior-drawing-standards` when a symbol or material convention is uncertain, when Canadian/Vancouver applicability matters, or when the user asks for a standards check. Treat its result as interpretation and review support. It may not silently restyle the customer drawing or redesign geometry.

Inspect the actual source and current files before relying on a prior report. Establish which drawing controls geometry, which examples control style, and which user corrections amend the source. Do not copy geometry or labels from style examples.

Require evidence for structural boundaries. Derive directional edges from polygons. Bind dimensions to actual witness-line endpoints, use exact arithmetic, and keep internal observations distinct from customer dimensions. Preserve uncertainty internally. Display only necessary, resolved inferred dimensions through a bound annotation layout on pale yellow; keep redundant or unresolved residuals out of customer-facing drawings.

Generate all formats from the same geometry and resolved layout. Compare the source and rendered artifacts, not only equations or saved pass flags. Keep automated verification and actual visual review separate; never mark unperformed review passed.

## Verified automatic learning

The owner has authorized narrow, verified improvements to this skill during future uses. This is not a background service and grants no permissions beyond the active environment. Only change this skill and its learning records; never modify unrelated skills, settings, or general memories.

Distinguish reusable invariants, user preferences, and project facts. Keep project facts in the project. Retain unverified or conflicting lessons as candidates. Use the versioned helper described in evolution.md; take a fresh fingerprint before preparing edits and stop if another writer changed the skill. Do not weaken acceptance requirements merely to make an output pass. Report adopted changes briefly with the drawing result.
