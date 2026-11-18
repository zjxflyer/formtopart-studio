# Viewing, annotation layers and portable delivery

## Source-owned operation symbols

Render retained records using their own endpoints, owner face, orientation, convergence, segment count and pattern. Already-separated source dash fragments use ordinary solid strokes for each fragment; applying another dash pattern erases source segments. Apply a dashed material only to an unsegmented record whose pattern requires it. Never manufacture symbols from material or cabinet type.

Use a dedicated nonphysical layer. Compute facing from the owner's transformed face normal, update it as the camera moves, and depth-test against foreground objects. Respect hidden/isolate ancestry and project-specific view eligibility; do not draw on the back of a door or through an unrelated solid. Use the project's actual face basis, not a hardcoded axis from a prior example. For this simplified workflow, plan checking drafts omit operation symbols; supported elevation drafts and newly exported checking SVGs follow the display toggle.

Keep option state independent of dimensions, text, view labels and materials. Toggling display creates no model/database revision and does not alter original PDF evidence or delivered historical drawings. Unsupported-symbol projects show a disabled, explained control; they do not acquire generic marks. Preserve the same option semantics in the live viewer, offline viewer and WebGL fallback.

## Interaction and offline HTML

Provide orbit/pan/zoom, fit/focus, plan and source-matched elevation cameras. Project screen labels in a way that remains readable under display scaling; inspect actual clipping and overlap, not only CSS properties. Keep dimensions distinguishable from physical outlines and clear of them.

Export read-only HTML when requested: embed solved project data and required runtime/assets so the file does not depend on the local backend, login, API key or a remote CDN. Preserve orbit, cameras and independent display controls, but omit editing, import, commit and paid analysis actions. Preserve the previous export recoverably. Verify the downloaded file itself, not just the application's export button.

When WebGL is unavailable, clearly disclose the fallback; a static or SVG checking view must not masquerade as successful interactive 3D. Exercise controls that remain available in that fallback. Phone-sized browser emulation supports a limited usability claim, not verified opening of local HTML on physical iPhone/Android devices. File-manager preview behavior may differ from a full browser; test the intended sharing/opening route before promising device compatibility.

For wording-only changes, centralize visible, tooltip and accessibility strings across consumers. Keep internal fields, rendering, defaults, APIs and model/history unchanged. Update current instructions and selectors without rewriting historical reports; clarify symbols versus mechanical animation.

## Independent viewing and size controls

Do not reuse source-drawing include/exclude lists as ordinary model-camera visibility rules. Keep full-model geometry inclusion separate from source-bound annotation eligibility and explicit framing policy; still respect hide/isolate, normal occlusion and view-specific annotation limits. Source checking drawings retain their own filters. For this owner's viewer, source-linked camera selection centers/fits visible physical geometry including room context, whereas quick directions preserve pivot and scale. Verify the actual fallback projection under the same representation policy and disclose its non-3D limitations.

An explicit component-size switch must gate all size overlays consistently, including projects or subjects without registered relationship dimensions. Relationship dimensions remain independent. In selected mode, show only the selected object's or assembly's existing overall size records, not descendant-part sizes or invented measurements. Show selection name/ID and readable width/height/depth labels; explain dimensions-off, no selection, hidden selection, missing overall records and edge-on/too-small projections. Disabled controls need an explanation. Share these semantics and accessibility wording across live, portable and checking/fallback consumers; inspect actual toggle results, not just the option value.
