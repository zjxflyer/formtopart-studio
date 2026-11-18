# Customer symbol profile

## Independent endpoint checks

Check each corrected symbol against its source crop independently of the generated inventory. Validate both recorded endpoints, segment count, convergence point, direction, pattern, and owner. A contained reversed mark is still wrong. Render explicit endpoints through a shared mapping; do not silently substitute a generic orientation for a corrected owner.

Component identity and notation are separate evidence. A drawer has linear access semantics when confirmed, but the number and slope of its marks follow the project symbol profile. A single diagonal is not a universal drawer convention. Likewise, a visible chevron does not by itself establish a physical hinge, rotation center, or pair of doors.

For adjacent door faces, keep one operation-symbol record per owner. Do not collapse two owner-specific polylines into a combined V, diamond, or generic mark even when their rendered endpoints meet. For drawers, retain every source-supported access mark through simplification; record and verify its owner, orientation, endpoints, segment count, and dash pattern independently.

Distinguish an unsegmented dashed path from already-separated native dash fragments. Draw each recorded fragment as its exact stroke; applying a second dash pattern can erase supported segments. Audit this distinction in every requested renderer/export. Interactive display preferences belong to the 3D companion and do not silently suppress symbols in delivered static elevations.


Read the drawing set before reconstruction: legends and general notes first, then coordinated plans, elevations, sections, details, schedules, and repeated usage. Record the source page or region for every symbol class used in the output.

Build a project symbol profile with at least:

- physical visible edges and confirmed seams;
- hidden or overhead lines;
- opening, operation, hinge, or access marks;
- material hatches, grain, directional patterns, and surface textures;
- centre, grid, break, section, elevation, detail, revision, and reference marks;
- dimension, extension, witness, leader, and terminator styles;
- line pattern, weight, orientation, owner face, clipping boundary, and source evidence.

Classify source marks before deciding their output:

- `real_boundary`: a solid edge, seam, panel break, rail, opening edge, return, toe kick, or material boundary supported by structural evidence.
- `opening_operation`: a component-owned mark that describes access or movement. Record its source-supported appearance and direction. Add a hinge, swing, or rotation reference only with independent evidence. For a drawer, retain the project's opening notation without assigning a rotation arc.
- `annotation`: dimensions, witness lines, leaders, material labels, and reference symbols. These are not component geometry.
- `texture_or_surface_detail`: grain, stone speckle, hatch, lighting texture, or similar appearance-only detail that may be omitted after physical boundaries and material relationships are preserved.

Store each retained or omitted mark as a symbol record with this minimum shape:

```json
{
  "id": "symbol-...",
  "kind": "real_boundary|opening_operation|annotation|texture_or_surface_detail",
  "owner_component": "component-id-or-null",
  "owner_face": "face-id-or-null",
  "start": [0, 0],
  "end": [0, 0],
  "orientation": "horizontal|vertical|diagonal|radial|other",
  "direction": "source-direction-or-null",
  "line_pattern": "solid|dashed|dash-dot|leader|other",
  "operation": "hinged_door|drawer|none|unresolved",
  "appearance_confidence": 0.0,
  "meaning_confidence": 0.0,
  "evidence": ["source-page-or-region"],
  "decision": "retain|simplify|omit"
}
```

The record keeps appearance confidence separate from meaning confidence. A visible X, V, or diagonal can be reproduced faithfully while its precise operation remains unresolved. A mark cannot create a divider, door, drawer, material area, or dimension without independent evidence.

Use evidence in this order: explicit customer legend or note; corroborating views, details, and schedules; consistent use within the drawing set; applicable project requirements; external industry or software convention. External convention explains gaps but does not override clear project evidence.

Track `appearance_confidence` separately from `meaning_confidence`. A visible X, V, W, diamond, or diagonal can be reproduced accurately while its precise operation remains unresolved. Preserve the visible mark as a source symbol when useful, record possible meanings, and request confirmation when meaning affects scope. Do not convert the mark into a divider, pair of doors, brace, opening, or material area without evidence for that physical condition.

Material and symbol are independent attributes. Wood classification alone does not generate dash-dot or opening marks. Fixed rails, returns, closeouts, toe kicks, panels, mirror fields, glass faces, metal faces, and stone faces receive only source-supported marks. The same opening symbol may legitimately occur on different materials.

Simplify dense texture only after preserving physical boundaries, material relationships, direction where relevant, and recognizable operation. Keep confirmed seams as geometry even when nearby operation marks are omitted or simplified. Clip every retained mark to its owning face unless the source intentionally crosses the boundary.

When a customer elevation and a colorful or 3D view disagree, use the dimensioned elevation and coordinated dimensions as the geometry authority. Use the other view to confirm identity, operation, material relationship, or a blurred detail. Do not import a boundary that is absent from the dimensioned source.

When interpretation remains uncertain, consult `$interior-drawing-standards` and store its evidence, applicability, confidence, and confirmation needs. A standards finding may create a review flag; it may not directly mutate geometry.
