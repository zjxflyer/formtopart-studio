# Separation validation

Start with a passing clean extraction before applying mutations.

Keep these results independent:

1. **Selection scope:** included and excluded components match the contract.
2. **Recursive integrity:** all selected descendants and no excluded branches
   appear in the extracted model.
3. **Geometry equivalence:** parent and local contours match after reversing the
   recorded transform.
4. **Topology:** visible edges, shared-edge decisions, adjacency, and openings
   remain supported.
5. **Symbol ownership:** every retained symbol remains attached to its owner and
   keeps the same owner-local coordinates.
6. **Dimensions:** retained measurements preserve values and endpoint identity;
   derived overall values have complete evidence and graphics.
7. **Source verification:** inspect controlling source evidence independently.
   Record source references, findings, unresolved issues, and reviewed artifact
   hashes separately. Parent-model agreement, visual review, and repeatability
   do not prove it; a stale reviewed hash must fail.
8. **Artifacts:** inspect actual vector edges, labels, and rasterized outputs;
   compare two independent builds. Compare exported coordinates, complete
   contours, junctions, colours, and dash styles against the extracted model.

Exercise different inclusion contracts, including plinth excluded and included,
and a nested nonrectangular assembly. The method must derive inventory counts
from the selection rather than expect a cabinet-specific number.

Mutations should change observable output or model behavior: include an excluded
component, omit a selected child, resize a contour, reorder a nonrectangular
polygon, move a symbol relative to its owner, drop an exposed boundary, retain a
cross-scope dimension, or break a local endpoint binding. Every applicable
mutation must fail. Include export-only missing/shortened boundaries and wrong
edge styles while leaving the extracted model correct.

