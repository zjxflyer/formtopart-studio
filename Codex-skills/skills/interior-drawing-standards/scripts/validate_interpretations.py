"""Validate interpretation records without asserting that an interpretation is true."""
import argparse
import json
from pathlib import Path


SOURCE_CLASSES = {
    "mandatory",
    "project-requirement",
    "specified-standard",
    "industry-guidance",
    "software-convention",
    "customer-specific-notation",
    "project-inference",
}


def validate_record(record):
    required = {
        "id",
        "project_context",
        "appearance",
        "possible_interpretations",
        "meaning_confidence",
        "geometry_effect",
        "material_effect",
        "dimension_effect",
        "source_class",
        "confirmation_needed",
        "compliance_flags",
    }
    missing = sorted(required - record.keys())
    if missing:
        raise ValueError(f"{record.get('id', '<unknown>')}: missing {missing}")
    appearance = record["appearance"]
    for key in ("class", "shape", "line_pattern", "orientation", "owner_face", "appearance_confidence"):
        if key not in appearance:
            raise ValueError(f"{record['id']}: missing appearance.{key}")
    for key, value in (("appearance_confidence", appearance["appearance_confidence"]), ("meaning_confidence", record["meaning_confidence"])):
        if not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise ValueError(f"{record['id']}: {key} must be between 0 and 1")
    if record["source_class"] not in SOURCE_CLASSES:
        raise ValueError(f"{record['id']}: invalid source_class")
    if not isinstance(record["possible_interpretations"], list) or not record["possible_interpretations"]:
        raise ValueError(f"{record['id']}: possible interpretations required")
    if not isinstance(record["compliance_flags"], list):
        raise ValueError(f"{record['id']}: compliance_flags must be a list")
    for effect in ("geometry_effect", "material_effect", "dimension_effect"):
        if record[effect] != "none":
            raise ValueError(f"{record['id']}: symbol records cannot directly change {effect}")


def validate_document(document):
    if document.get("schema_version") != 1:
        raise ValueError("Unsupported schema_version")
    records = document.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("records must be a non-empty list")
    ids = set()
    for record in records:
        validate_record(record)
        if record["id"] in ids:
            raise ValueError(f"Duplicate id: {record['id']}")
        ids.add(record["id"])
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    records = validate_document(json.loads(args.path.read_text(encoding="utf-8")))
    print(f"Validated interpretation records: {len(records)}")


if __name__ == "__main__":
    main()
