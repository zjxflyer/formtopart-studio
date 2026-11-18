# Source and structure

## Correcting an inherited drawing

Start with the customer's marked region: record orientation, endpoints, intended appearance, and the source crop before choosing an owner or datum. Recheck the complete source face; inherited IDs are hypotheses, not evidence of separate components. When merging faces, retire old owners and symbols, rebind dependent dimensions, and recalculate union area and adjacency.

Before editing, define a bounded correction: required features and source dimensions, affected consumers, permitted changed records/regions, and protected outputs. Stage in the requested new revision directory with an isolated database where applicable; exploratory attempts must not create customer-history revisions. Use the 3D companion's verification procedure when a feature exists in data but is not visible.

Trace every coincident edge contributor and dependent annotation. Apply a symbol, visible-edge, or physical-geometry correction at that layer, then compare the normalized visible geometry against the source and baseline. Two visible spans may have more than two contributing primitives. Trim intervals on all contributors, preserving their unaffected portions and nearby witness lines. Inspect a small affected-view preview, including distinctive internal contours, before full-set generation; an object's bounds alone cannot establish its recognizable shape.

Closed material polygons support area calculations; their internal partitions do not automatically authorize visible seams. Keep a resolved visible-edge representation separate from those polygons. Preserve an existing source-supported appliance outline even when a new inferred outline is rejected. Appliance identity alone supplies no footprint.

Assembly or group bounds establish ownership, hierarchy, and extents; they do not automatically authorize a visible perimeter or opaque fill. Give each visible fill and physical edge an evidenced owner. When child components intentionally leave open intervals, keep those intervals blank unless separate source evidence identifies a continuous backing or floor component. Attach material labels to their actual rendered owners; a material code does not create geometry across gaps.


Establish source authority for geometry, materials, dimensions, and symbols. Record source page/region and approved amendments. Images teaching material recognition or annotation style cannot supply project geometry.

Read legends, notes, coordinated plans, elevations, sections, details, and schedules before reconstructing a view. Establish the project symbol profile described in [source-symbols.md](source-symbols.md). Symbols and textures are representation records attached to owner faces; they are not physical geometry unless the source independently confirms an edge, seam, opening, or component.

Recognize connected parent assemblies before faces. Include doors, side panels, dividers, rails, frames, closeouts, returns, toe kicks, appliance openings, mirror fields, and LED bands when supported. Represent material regions as polygons and components as recursive children. Preserve L-shaped contours and segment order.

Do not infer a structural division merely from symmetry. First establish the boundary from source evidence. When removing an unsupported boundary, remove or rebind dependent dimensions and schedule records too.

For every polygon, derive every edge, direction, solved endpoints, adjacency, evidence, and confirmation status. Nonrectangular shapes need all directional segments, not a bounding rectangle. Check narrow members and upper/lower/left/right neighbors; distinguish intended openings from omissions. Compare shared edges, gaps, overlaps, and continuity. Never accept cached pass flags as evidence.

Preserve non-wood positions and general shapes even when their interiors are blank. Keep uncertain classifications internal; do not label an entire region as mirror from a leader identifying only a local target. Trace continuous features to source-supported endpoints. Model a toe kick or plinth recess as an explicit component whenever the source contour supports it, even when its witness has no readable number. Toe kicks must stop at openings where the source shows interruption.

Cross-view inference requires evidence that the compared contours represent the same physical component. When that correspondence is established, store one shared provisional value, derivation method, source regions, confidence, and unresolved alternatives; do not turn a repeated project value into a universal toe-kick or rail default.

When a cross-view residual identifies a short toe-kick or plinth recess, bind it only to the corresponding witness endpoints. Build the stepped end into the owner polygon instead of approximating it with an inset face rectangle. Preserve confirmed neighboring spans by translating their dependent components and annotations together; do not stretch them to absorb the residual. Do not mirror a step to another end without independent evidence.

Distinguish cabinet toe kicks from wall bases and similar context details. A wall-base junction belongs to the wall component even when it occurs near a cabinet plinth or shares a height. Preserve the wall's side boundaries and the source-supported horizontal junction; never convert it into cabinet geometry merely because both are close to the floor.

Treat dimensioned walls, returns, ceilings, soffits, and similar surrounding conditions as context components rather than page decoration. Derive their visible edges from the same component bounds or polygons used by the model. Reconstruct the complete connected source contour before resolving local endpoints. Record intentional openings; otherwise require the expected perimeter edges and exact corner connections. An annotation fragment or isolated dimension value does not authorize a physical notch or opening without a supporting boundary. Context edges remain independent from cabinet seams and dimension witness lines.

New projects determine their own component inventory, datums, materials, symbols, and units. The historical cabinet counts and dimensions are not constraints for another drawing.
