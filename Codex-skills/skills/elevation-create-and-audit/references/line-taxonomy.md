# Customer line taxonomy

## Visibility versus material closure

A polygon edge becomes a visible physical stroke only with source support. For a local deletion, enumerate all coincident contributors and subtract the target interval from each; test the final stroke coverage independently of owner IDs. Keep annotation lines distinct from object strokes in that test. Compare appearance with the marked source before accepting a primitive-count assertion.

Operation mark shape and count are project-specific. Use source-supported drawer notation without a rotation interpretation; never generate a door chevron merely because a face is wood or belongs to a base cabinet.


Read this reference before converting a customer drawing into a simplified elevation.

## Classification order

Inspect the source in this order: explicit legend and notes; solid physical edges and dimension witness lines; coordinated views and schedules; repeated symbol usage; colorful or 3D supporting references; external convention. Keep the source region for every decision.

1. `real_boundary` is geometry. It includes supported object outlines, seams, panel breaks, rails, returns, toe kicks, openings, and visibly evidenced material junctions. Derive candidate edges from the owner polygon, but do not stroke every material-region perimeter automatically. Preserve supported physical edges even if nearby texture is removed.
2. `opening_operation` belongs to an owner face. Record source-supported endpoints, direction, pattern, and segment count. Drawer notation has no rotation interpretation; its shape follows the project evidence. A door mark establishes hinge or swing meaning only when corroborated. Do not infer a physical divider from an X or V alone.
3. `annotation` explains geometry. It includes dimensions, extension and witness lines, leaders, material labels, and reference bubbles. Bind dimensions to true endpoints and keep labels separate from component geometry.
4. `texture_or_surface_detail` is appearance-only. It includes wood grain, stone speckle, hatch, lighting texture, and rendering artifacts. Omit it from the clean elevation unless it also carries independent boundary or operation evidence.

## Supporting references

The colorful or 3D reference can resolve what a blurred area represents and can confirm that a component is a door, drawer, appliance, stone, mirror, metal, or wood. It cannot invent a line, seam, opening, dimension, or material area that the dimensioned elevation does not support. If the appearance is clear but the meaning is uncertain, retain the appearance with low meaning confidence and flag it for review.

## Acceptance rules

Every retained real boundary needs source evidence and an owner. Every retained operation mark needs an owner, endpoints, orientation, line pattern, and confidence. Every omitted feature needs its actual classification and exclusion reason: supported but out-of-scope context is not unsupported geometry. Marks must be clipped to their owner face unless the source explicitly crosses it. Component counts, material areas, adjacency, and dimension equations must be unchanged by symbol simplification. Apply the inclusion and negative-coverage procedure in [simplification.md](simplification.md).
