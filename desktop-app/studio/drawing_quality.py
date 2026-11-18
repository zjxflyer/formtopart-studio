"""Per-view readiness; a populated tree or a page header is not a drawing."""
from __future__ import annotations


def attach_drawings(model, scene):
    if model.drawings or model.requires_source_drawings:
        from .drafting import assess_drawings, render_svg
        from .drawing_state import source_2d_model
        source_model=source_2d_model(model)
        resolved=scene['resolved']
        if model.source_2d_binding is not None:
            from .geometry import Resolver
            resolver=Resolver(source_model)
            resolved={p.id:resolver.parameter(p.id)[0] for p in source_model.parameters}
        quality = assess_drawings(source_model.drawings, resolved, [v.id for v in source_model.views])
        records = {v["id"]: v for v in quality["views"]}
        from .drawing_state import semantic_fingerprint
        fingerprint = semantic_fingerprint(source_model)
        for view in model.drawings:
            record = records[view.id]
            if view.semantic_snapshot is None:
                if record["status"] == "ready":
                    record["status"] = "needs_review"
                record["issues"].append("This drawing lacks a semantic design snapshot; regenerate and review it before acceptance.")
            elif view.semantic_snapshot != fingerprint:
                record["status"] = "stale"
                record["issues"].append("Geometry, material, ownership or source-view mapping changed; regenerate this source drawing.")
        priority = {"ready": 0, "needs_review": 1, "stale": 2, "incomplete": 3}
        quality["status"] = max((record["status"] for record in quality["views"]), key=lambda status: priority[status], default="incomplete")
        quality["issues"] = [f"{record['label']}: {issue}" for record in quality["views"] for issue in record["issues"]] or quality["issues"]
        scene["drawings"] = {
            view.id: {**records[view.id], "owner_ids": view.owner_ids, "svg": render_svg(view),
                      "source_units": True, "coordinate_system": "source-local NTS"}
            for view in model.drawings
        }
        scene["drawing_quality"] = quality
        return scene
    # Backward compatible legacy models are inspected in each actual source view.
    # This also diagnoses the user's pre-fix candidate without changing its model.
    records = []
    for view in model.views:
        definition = scene["views"][view.id]
        include = set(definition.get("include", []))
        eligible = [m for m in scene["meshes"] if not include or m["id"] in include]
        count = 0
        for mesh in eligible:
            projected = [[sum(p[i] * basis[i] for i in range(3)) for basis in (view.right, view.up)]
                         for p in mesh["vertices"]]
            if projected and all(max(p[i] for p in projected)-min(p[i] for p in projected) > .001 for i in range(2)):
                count += 1
        issues = [] if count else ["No drawable geometry in this required view. Re-analyze the original source. / 此必需视图没有可绘制几何，请重新分析原图。"]
        records.append({"id": view.id, "label": view.label, "kind": view.kind,
                        "status": "ready" if count else "incomplete", "issues": issues,
                        "geometry_count": count, "dimension_count": 0, "symbol_count": 0,
                        "owner_ids": view.include, "review_status": "legacy"})
    incomplete = any(v["status"] == "incomplete" for v in records)
    scene["drawings"] = {}
    scene["drawing_quality"] = {"status": "incomplete" if incomplete or not scene["meshes"] else "ready",
                                "views": records,
                                "issues": [issue for v in records for issue in v["issues"]],
                                "model_preview": True, "can_apply": bool(scene["meshes"])}
    return scene
