from __future__ import annotations

import copy
import json


def parent_model() -> dict:
    return {
        "components": {
            "cabinet": {"parent": None, "polygon": [(10, 5), (20, 5), (20, 25), (10, 25)]},
            "rail": {"parent": "cabinet", "polygon": [(10, 23), (20, 23), (20, 25), (10, 25)]},
            "face": {"parent": "cabinet", "polygon": [(10, 8), (20, 8), (20, 23), (10, 23)]},
            "plinth": {"parent": "cabinet", "polygon": [(10, 5), (20, 5), (20, 8), (10, 8)]},
        },
        "symbol": {"owner": "face", "points": [(11, 9), (19, 15), (11, 22)]},
        "dimensions": {
            "width": {"start": (10, 5), "end": (20, 5), "value": 10},
            "face-height": {"start": (10, 8), "end": (10, 23), "value": 15},
            "external": {"start": (0, 0), "end": (10, 5), "value": 15},
        },
        "visible_edges": {"left", "right", "top", "bottom", "rail-bottom", "face-bottom"},
    }


def translate_polygon(points, dx, dy):
    return [(x + dx, y + dy) for x, y in points]


def extract(parent: dict, include_plinth: bool) -> dict:
    selected = {"cabinet", "rail", "face"} | ({"plinth"} if include_plinth else set())
    dx, dy = -10, (-5 if include_plinth else -8)
    components = {
        key: {"parent": value["parent"], "polygon": translate_polygon(value["polygon"], dx, dy)}
        for key, value in parent["components"].items() if key in selected
    }
    symbol = copy.deepcopy(parent["symbol"])
    symbol["points"] = translate_polygon(symbol["points"], dx, dy)
    dimensions = {}
    allowed_parent_points = {
        point
        for key, item in parent["components"].items()
        if key in selected
        for point in item["polygon"]
    }
    for key, value in parent["dimensions"].items():
        if value["start"] in allowed_parent_points and value["end"] in allowed_parent_points:
            dimensions[key] = {
                **value,
                "source_id": key,
                "start": (value["start"][0] + dx, value["start"][1] + dy),
                "end": (value["end"][0] + dx, value["end"][1] + dy),
            }
    return {
        "selected": selected,
        "components": components,
        "symbol": symbol,
        "dimensions": dimensions,
        "transform": [dx, dy],
        "visible_edges": set(parent["visible_edges"]),
        "include_plinth": include_plinth,
    }


def normalize(points, transform):
    dx, dy = transform
    return [(x - dx, y - dy) for x, y in points]


def validate(parent: dict, result: dict) -> list[str]:
    errors = []
    expected = {"cabinet", "rail", "face"} | ({"plinth"} if result["include_plinth"] else set())
    if result["selected"] != expected or set(result["components"]) != expected:
        errors.append("selection scope mismatch")
    for key, item in result["components"].items():
        if normalize(item["polygon"], result["transform"]) != parent["components"][key]["polygon"]:
            errors.append(f"geometry changed: {key}")
    owner = result["symbol"]["owner"]
    if owner not in result["components"]:
        errors.append("symbol owner missing")
    if normalize(result["symbol"]["points"], result["transform"]) != parent["symbol"]["points"]:
        errors.append("symbol-local coordinates changed")
    if "external" in result["dimensions"]:
        errors.append("cross-scope dimension retained")
    for key, dim in result["dimensions"].items():
        source = parent["dimensions"][key]
        if dim["value"] != source["value"] or normalize([dim["start"], dim["end"]], result["transform"]) != [source["start"], source["end"]]:
            errors.append(f"dimension binding changed: {key}")
    if result["visible_edges"] != parent["visible_edges"]:
        errors.append("visible boundary coverage changed")
    return errors


def nonrectangular_case() -> dict:
    parent = [(4, 3), (12, 3), (12, 7), (8, 7), (8, 14), (4, 14)]
    child = [(5, 4), (7, 4), (7, 12), (5, 12)]
    local = translate_polygon(parent, -4, -3)
    local_child = translate_polygon(child, -4, -3)
    return {
        "parent": parent,
        "child": child,
        "local": local,
        "local_child": local_child,
        "round_trip": translate_polygon(local, 4, 3),
        "child_round_trip": translate_polygon(local_child, 4, 3),
    }


def run() -> dict:
    parent = parent_model()
    without_plinth = extract(parent, False)
    with_plinth = extract(parent, True)
    assert validate(parent, without_plinth) == []
    assert validate(parent, with_plinth) == []
    l_shape = nonrectangular_case()
    assert l_shape["round_trip"] == l_shape["parent"]
    assert l_shape["child_round_trip"] == l_shape["child"]

    mutations = []
    cases = {
        "wrong-scope": lambda r: r["components"].__setitem__("plinth", copy.deepcopy(parent["components"]["plinth"])),
        "resized-component": lambda r: r["components"]["face"]["polygon"].__setitem__(1, (11, 0)),
        "moved-symbol": lambda r: r["symbol"]["points"].__setitem__(0, (9, 9)),
        "missing-boundary": lambda r: r["visible_edges"].remove("left"),
        "broken-dimension": lambda r: r["dimensions"]["face-height"].__setitem__("value", 14),
    }
    for name, mutate in cases.items():
        candidate = copy.deepcopy(without_plinth)
        mutate(candidate)
        mutations.append({"id": name, "detected": bool(validate(parent, candidate))})
    assert all(item["detected"] for item in mutations)
    return {
        "status": "passed",
        "scope_without_plinth": sorted(without_plinth["selected"]),
        "scope_with_plinth": sorted(with_plinth["selected"]),
        "nonrectangular_round_trip": True,
        "mutations": mutations,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))

