---
name: drawing-add-objects
description: Add, insert, or replace physical objects in evidence-based customer drawing models while preserving affected component sizes, owned symbols, dimensions, and layout constraints. Use for requested construction additions; do not use for merely extracting an existing object.
---

# Add objects to drawings

Use this skill when a customer requests a new physical object or replaces an
existing object in a plan, elevation, or section.

Apply `$elevation-create-and-audit` for source classification, dimension style,
rendering, and artifact review. This skill supplies the transformation rules for
the addition itself.

Before changing geometry, read [workflow.md](references/workflow.md). Before
acceptance, read [validation.md](references/validation.md).

Record the requested contour, attachment points, material evidence, dimensions,
and whether each fact comes from the source or a user amendment. Classify the
operation as insertion, replacement, or placement in an existing gap. Solve the
space actually consumed, including required clearances; do not equate object
width with translation unless the constraints produce that result.

Choose the fixed assembly and compute the complete affected closure. Move every
affected component together with its descendants, owned symbols, material
regions, labels, and bound dimension endpoints. Preserve existing sizes unless
the user explicitly requests resizing. If a fixed envelope cannot accept the
addition under the authorized constraints, report the conflict instead of
silently compressing neighbouring objects.

Render complete physical boundaries and bind every displayed measurement to a
dimension record. Treat customer-specified values as amendments. Use the shared
drawing skill's inference presentation only for necessary resolved values.

Compare the result with a clean baseline and the controlling source. Keep model
consistency, source verification, visual review, and repeatability as separate
results.

