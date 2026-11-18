from __future__ import annotations

import copy
import json
from pathlib import Path


def solve_space(width: float, gap: float, clearance_left: float = 0.0,
                clearance_right: float = 0.0, fixed_envelope: bool = False) -> dict:
    required = width + clearance_left + clearance_right
    displacement = max(0.0, required - gap)
    if fixed_envelope and displacement > 0:
        return {"status": "conflict", "required": required, "displacement": displacement}
    return {"status": "fit", "required": required, "displacement": displacement}


def solve_replacement(new_width: float, replaced_width: float,
                      fixed_envelope: bool = False) -> dict:
    displacement = max(0.0, new_width - replaced_width)
    if fixed_envelope and displacement > 0:
        return {"status": "conflict", "displacement": displacement}
    return {"status": "fit", "displacement": displacement}


def baseline_model() -> dict:
    return {
        "components": {
            "fixed": {"left": 0.0, "right": 10.0, "bottom": 0.0, "top": 20.0},
            "moving": {"left": 14.0, "right": 24.0, "bottom": 0.0, "top": 20.0},
            "moving-child": {"left": 16.0, "right": 18.0, "bottom": 2.0, "top": 18.0,
                             "parent": "moving"},
            "inserted": {"left": 10.0, "right": 14.0, "bottom": 0.0, "top": 20.0},
        },
        "original_components": {
            "moving": {"left": 10.0, "right": 20.0, "bottom": 0.0, "top": 20.0},
            "moving-child": {"left": 12.0, "right": 14.0, "bottom": 2.0, "top": 18.0,
                             "parent": "moving"},
        },
        "translation": 4.0,
        "symbol": {"owner": "moving", "start": [12.0, 4.0], "end": [18.0, 16.0], "original_start": [8.0, 4.0], "original_end": [14.0, 16.0]},
        "dimension": {"start_component": "inserted", "endpoints": [10.0, 14.0], "value": 4.0},
        "inserted_edges": {"left", "right", "top", "bottom"},
    }


def validate_model(model: dict) -> list[str]:
    errors = []
    delta = model["translation"]
    for key in ("moving", "moving-child"):
        moved = model["components"][key]
        original = model["original_components"][key]
        if moved["right"] - moved["left"] != original["right"] - original["left"]:
            errors.append(f"component resized: {key}")
        if moved["top"] - moved["bottom"] != original["top"] - original["bottom"]:
            errors.append(f"component height changed: {key}")
        if moved["left"] != original["left"] + delta or moved["right"] != original["right"] + delta:
            errors.append(f"component did not translate with closure: {key}")
    symbol = model["symbol"]
    if symbol["start"] != [symbol["original_start"][0] + delta, symbol["original_start"][1]]:
        errors.append("owned symbol did not translate")
    if symbol["end"] != [symbol["original_end"][0] + delta, symbol["original_end"][1]]:
        errors.append("owned symbol endpoint did not translate")
    inserted = model["components"]["inserted"]
    if model["dimension"]["endpoints"] != [inserted["left"], inserted["right"]]:
        errors.append("dimension endpoints are not bound to inserted component")
    if inserted["right"] - inserted["left"] != model["dimension"]["value"]:
        errors.append("dimension value mismatch")
    if model["inserted_edges"] != {"left", "right", "top", "bottom"}:
        errors.append("inserted contour incomplete")
    return errors


def run() -> dict:
    decisions = {
        "fits_gap": solve_space(4, 6),
        "requires_translation": solve_space(4, 0),
        "fixed_envelope_conflict": solve_space(4, 0, fixed_envelope=True),
        "uses_clearance": solve_space(4, 3, 0.5, 0.5),
        "replacement": solve_replacement(6, 4),
    }
    assert decisions["fits_gap"] == {"status": "fit", "required": 4.0, "displacement": 0.0}
    assert decisions["requires_translation"]["displacement"] == 4.0
    assert decisions["fixed_envelope_conflict"]["status"] == "conflict"
    assert decisions["uses_clearance"]["displacement"] == 2.0
    assert decisions["replacement"] == {"status": "fit", "displacement": 2}

    clean = baseline_model()
    assert validate_model(clean) == []
    mutations = []
    cases = {
        "resized-neighbour": lambda m: m["components"]["moving"].__setitem__("right", 25.0),
        "unmoved-symbol": lambda m: m["symbol"].__setitem__("start", [8.0, 4.0]),
        "partial-subtree-move": lambda m: m["components"]["moving-child"].update({"left": 12.0, "right": 14.0}),
        "missing-boundary": lambda m: m.__setitem__("inserted_edges", {"left", "right", "top"}),
        "broken-dimension-binding": lambda m: m["dimension"].__setitem__("endpoints", [10.0, 13.0]),
    }
    for name, mutate in cases.items():
        candidate = copy.deepcopy(clean)
        mutate(candidate)
        mutations.append({"id": name, "detected": bool(validate_model(candidate))})
    assert all(item["detected"] for item in mutations)
    return {"status": "passed", "decision_cases": decisions, "mutations": mutations}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))

