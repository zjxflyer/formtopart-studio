# Addition validation

Start fault injection only after the unmodified candidate passes its model,
geometry, annotation, and export checks.

Verify these independent results:

1. **Constraint solution:** operation mode, usable gap, clearances, displacement,
   fixed envelope, and conflict status are explicit.
2. **Size preservation:** every moved existing component keeps its original
   local contour and dimensions unless resizing was authorized.
3. **Closure preservation:** descendants, symbols, labels, and dimension
   endpoints receive the same transform as their owner.
4. **Topology:** the new component has complete physical boundaries and correct
   connections, gaps, occlusions, and adjacency.
5. **Annotations:** displayed values have records, structural endpoints, lines,
   witnesses, ticks, and labels; hidden values remain auditable.
6. **Evidence:** compare against the original source or explicit amendment.
   Record source references, findings, unresolved issues, and reviewed artifact
   hashes separately. Visual review and model checks cannot set source
   verification to passed; a stale reviewed hash must fail.
7. **Artifacts:** inspect actual vector edges and rasterized output; record
   repeatability separately. Compare exported coordinates, complete contours,
   junctions, colours, and dash styles against the resolved model.

Exercise at least these cases when validating the skill:

- an object fits within an existing gap with no translation;
- an insertion translates a complete neighbouring assembly;
- a fixed envelope produces a documented conflict;
- a replacement uses the net occupied-space change.

Mutations should alter observable model or exported behavior: resize a moved
neighbour, leave an owned symbol unmoved, omit one physical edge, break a
dimension binding, move only part of a recursive assembly, or conceal a fixed
envelope conflict. Include export-only missing/shortened edges and wrong edge
styles while leaving the canonical model correct. Every applicable mutation
must fail.

