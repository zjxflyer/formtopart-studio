# Rendering and customer output

## Simplification and local callouts

Simplify optional appliance interior graphics only after preserving independently supported envelope and coordination edges. Render thin construction from solved coordinates, with no arbitrary pixel inset at a controlling junction.

For a short thickness note, preserve exact witnesses and route the label into a nearby clear lane. Check the result against object strokes, operation marks, dimension lines, and labels. Do not bypass collision checks to force a preferred placement. Generate all formats and representation overlays from the same resolved visible edges and annotation layout.


Default style follows the owner's simplified factory-review profile in [simplification.md](simplification.md): solid black physical outlines, texture-free interiors, and source-supported black opening marks clipped to their owner faces in elevations. Retain a material/direction pattern only when explicitly necessary for the requested drawing, not merely because it exists in the source. Door or operation marks stop at their face boundaries, including rails and frames. Wood classification alone never creates a dash-dot mark, and a non-wood face may retain an opening mark when the source supports it. Do not use blue customer material notes or leaders. Audit overlays may use explanatory colors.

Draw structural and context geometry with solid black outlines. Use blue `#2563EB` as the owner's default for every dimension number, dimension line, witness or extension line, tick, and dimension leader. Confirmed values use a white or transparent background; necessary resolved inferred values use pale yellow. Show numeric values and units only, without visible `INF`. Retain uncertainty in data. Omit debug notes such as TBC and LEADER TARGET from customer output. Source-supported concise material notes remain black. Material codes, fraction format, font size, units, and dimension color remain overridable by explicit project requirements.

Where dimension graphics cross confirmed physical edges, render dimensions before black physical outlines and verify visible coverage in actual raster exports. Do not mask board caps or thickness intervals with blue strokes or label backgrounds. A patterned operation mark remains a separate annotation, never a substitute for a physical closing edge. Compare inner/outer thickness endpoints consistently; do not create a sloped cap by mixing endpoints from different contour levels.

Place surrounding dimension chains outside the complete visible object and context envelope. Keep a visible, scalable gap between objects and extension-line starts, move dimension lanes only as far outward as readability requires, and shorten excessive extensions by moving the complete lane closer. Historical pixel clearances are examples tied to their canvas size, not fixed cross-project geometry.

On coordinated plan/elevation sets, retain compact black source-linked view labels by default. Preserve their verified sheet/detail text and arrow directions, keep text comparable in readability to dimension labels, and resolve conflicts by adjusting the reference annotations rather than construction or dimension bindings. The source-linked references are an intentional exception to removing unrelated bubbles; an explicit user request to omit them still takes precedence.

Render connected contours, component edges and narrow members, permitted source symbols and any explicitly required patterns, then dimensions. Use one resolved layout and font metrics for SVG, PNG, PDF, and audit overlays. Match fill, dash, rotation, alignment, and clipping behavior across backends; use full six-digit hex colors to avoid inconsistent parser interpretation.

Export a clean PDF containing the main elevation and dimensions without large titles or lower audit/schedule boxes. Use vector lines and embedded fonts or equivalent resolution-independent glyphs. Preserve all external dimensions in the crop with readable margins. Supply schedules and diagnostic reports separately. Inspect a rasterized PDF, including enlarged narrow labels; embedding a low-resolution screenshot does not satisfy sharp-number output.
