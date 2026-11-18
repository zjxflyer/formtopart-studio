# Addition workflow

## Establish the request

Identify the requested object, its intended contour, position, connections,
material, dimensions, and display policy. Store each fact as source-supported,
user-amended, inferred, unresolved, or excluded. A user-specified size is an
amendment even when the source visually suggests the object.

Freeze the reviewed baseline and list the permitted changes before editing.
Inventory all owners whose geometry or annotations may change.

## Select the operation

- **Placement in a gap:** use existing free space. Translation is zero when the
  usable gap satisfies object width plus required clearances.
- **Insertion:** create space and translate an affected assembly. Required
  displacement is the unsatisfied occupied interval, not automatically the new
  object's width.
- **Replacement:** remove or supersede an existing owner, then solve the net
  space difference and rebind dependencies.

For a one-dimensional insertion, let `w` be object width, `g` usable gap, and
`c1 + c2` required clearances. The initial displacement candidate is
`max(0, w + c1 + c2 - g)`. Resolve additional constraints before applying it.

If the outer envelope is fixed, accept the operation only when the remaining
space and authorized resizing rules satisfy every component constraint. A
conflict remains a conflict; it must not become hidden distortion.

## Transform the model

Choose the fixed side and collect the affected closure:

- translated parent assemblies and recursive children;
- owned operation symbols and material regions;
- attached labels, leaders, and schedules;
- dimension endpoints and witness references;
- spanning context whose endpoint is authorized to move.

Apply one transform to the closure. Recompute adjacency and visible edges from
the transformed model. Preserve each unaffected width, height, contour, symbol
shape, and local symbol coordinate. Do not let the new material polygon create
an unsupported seam in a neighbour.

Create the new component with a stable ID, recursive placement, evidence, and
explicit amendment metadata. Derive all visible sides and junctions from its
contour. Record intentional openings and occlusions.

## Dimensions and output

Bind a displayed measurement to the new component's actual endpoints. Record a
customer value as `user_amendment`; it does not use inferred-value styling.
Store a non-displayed value with an explicit display policy. Rebind existing
dimensions after translation without changing their values.

Generate all output formats from the same solved geometry and annotation
layout. Compare the normalized unaffected regions with the baseline and inspect
the addition at whole-view and detail scales.

