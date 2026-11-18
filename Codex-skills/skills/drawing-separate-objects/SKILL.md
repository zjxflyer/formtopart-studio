---
name: drawing-separate-objects
description: Extract an existing recursive drawing assembly into a standalone plan, elevation, or section while preserving source identity, topology, owned symbols, and relevant dimensions. Use for isolated object views; do not use to redesign one object into new physical parts.
---

# Separate objects from drawings

Use this skill when a customer wants an existing object or assembly shown as an
independent drawing.

Apply `$elevation-create-and-audit` for evidence classification, dimension
style, rendering, and artifact review. This skill supplies selection,
extraction, coordinate normalization, and parent-comparison rules.

Before extracting, read [workflow.md](references/workflow.md). Before acceptance,
read [validation.md](references/validation.md).

Define the selected assembly and an explicit inclusion contract for rails, side
members, plinths, surrounding context, shared edges, annotations, and nested
children. Extract recursive components, evidence, visible edges, material
regions, and owned symbols. Preserve source IDs and store the transform from
parent coordinates to local coordinates.

Render from extracted records rather than object-specific edge lists or fixed
component counts. Retain dimensions whose structural endpoints belong to the
selection, rebind them to local datums, and document exclusions. Add an overall
dimension only when a verified chain or explicit amendment resolves it.

Treat a shared boundary according to its evidence and new visibility. Retain an
evidenced exposed boundary without inventing a new panel, thickness, or detail.

Compare normalized geometry, topology, and symbol-local coordinates with the
parent assembly. Verify the controlling source independently; a visual-status
flag or repeatable output cannot establish source accuracy.

If the request physically divides or redesigns the selected object, route it as
a new geometry request rather than a standalone extraction.

