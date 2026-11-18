# Interpretation records

Use a structured record so uncertainty cannot silently become geometry:

```json
{
  "id": "symbol-001",
  "project_context": {"jurisdiction": "Vancouver", "view": "elevation"},
  "appearance": {
    "class": "operation-mark",
    "shape": "V",
    "line_pattern": "dashed",
    "orientation": "apex-right",
    "owner_face": "face-12",
    "appearance_confidence": 0.98
  },
  "possible_interpretations": [
    {"meaning": "hinge-or-opening-direction", "confidence": 0.58, "evidence": ["repeated project usage"]}
  ],
  "meaning_confidence": 0.58,
  "geometry_effect": "none",
  "material_effect": "none",
  "dimension_effect": "none",
  "source_class": "customer-specific-notation",
  "confirmation_needed": "Confirm apex convention from hardware schedule or legend",
  "compliance_flags": []
}
```

Allowed source classes are `mandatory`, `project-requirement`, `specified-standard`, `industry-guidance`, `software-convention`, `customer-specific-notation`, and `project-inference`.

`geometry_effect`, `material_effect`, and `dimension_effect` default to `none`. A symbol-only record must keep them `none`. If a coordinated source independently confirms a physical condition, create or link a separate structural evidence record; do not promote the symbol itself into geometry evidence.

The example file [example-interpretations.json](example-interpretations.json) covers:

- the same X appearance with different project meanings;
- a V opening mark on wood and glass owner faces;
- clear appearance with unresolved meaning;
- an independently confirmed physical seam beside an operation mark.

When answering a user, summarize the likely interpretation in plain language, identify alternatives, state confidence, and say what evidence would resolve the ambiguity. Keep compliance observations in a separate section.
