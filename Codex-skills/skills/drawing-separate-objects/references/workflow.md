# Separation workflow

## Define the selection contract

Identify the selected parent assembly and state whether each adjacent or nested
class is included: rails, stiles, dividers, plinths, fillers, hardware,
appliances, wall or ceiling context, material regions, operation symbols, and
annotations. Resolve visible ambiguity from source evidence or an explicit user
choice. Do not let an image crop silently determine the semantic scope.

Record excluded objects and dimensions. A standalone view is an extraction of
existing geometry. A request that creates new physical divisions or parts is a
geometry change and needs separate authorization and evidence.

## Extract recursive records

Walk the selected assembly recursively and retain:

- component IDs, parent-child relationships, contours, datums, and evidence;
- resolved visible edges and intentional openings;
- owned operation symbols with owner-local coordinates;
- material regions and concise source-supported labels;
- dimensions and annotations that belong to the selection.

Choose a local origin and store the parent-to-local transform. Apply it to every
retained coordinate. Translation must not change widths, heights, segment
lengths, polygon order, adjacency, or symbol shape.

For shared edges, record the original owners and the standalone visibility
decision. Emit an already evidenced boundary when it becomes exposed. Do not
invent a back, side panel, thickness, return, or closing detail from the fact
that the neighbouring object was removed.

## Dimensions

Retain a source dimension when both structural endpoints belong to the selected
scope and the value describes the standalone object. Rebind its endpoints to
local datums while preserving source identity and value.

Omit dimensions owned by excluded objects or crossing beyond the selection;
store the reason. Derive a useful overall dimension only from a complete,
verified chain or an explicit user amendment. Store its formula, evidence,
status, and display policy. Necessary resolved inference follows the shared
drawing presentation rules.

## Render and compare

Use a generic traversal of component contours, visible-edge records, symbols,
and dimensions. Do not hardcode the selected object's component IDs, edge list,
symbol count, or dimension values in the renderer.

Normalize the parent and standalone geometry to the same origin and compare:

- component dimensions and contour segments;
- parent-child membership and adjacency;
- owned-symbol local coordinates and line patterns;
- retained dimension values and endpoint identities.

Inspect the standalone output and a parent-versus-result comparison. Verify the
original source separately from the parent model.

