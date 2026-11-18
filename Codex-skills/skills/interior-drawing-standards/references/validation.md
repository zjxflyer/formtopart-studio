# Validation

Validation has three distinct layers:

1. **Record validation:** required fields, confidence ranges, source classes, owner faces, and the rule that symbol-only evidence has no geometry, material, or dimension effect.
2. **Interpretation review:** evidence precedence, applicable jurisdiction and edition, plausible alternatives, limitations, and confirmation needs.
3. **Drawing review:** performed by `$elevation-create-and-audit`; confirms inventory, material areas, geometry, dimensions, seams, owner-face clipping, and recognizable rendering.

Required regression cases:

- identical X symbols with different documented meanings remain separate project interpretations;
- a V mark on wood and glass does not change either material classification;
- a clear diamond with unknown meaning is preserved without creating geometry;
- a confirmed seam remains structural even when an adjacent operation mark is removed;
- changing or deleting a symbol leaves component inventory, material area, and dimension equations unchanged;
- a standards warning appears as a review flag and does not mutate the customer drawing.

Run `python scripts/validate_interpretations.py references/example-interpretations.json`. Run the skill creator's `quick_validate.py` for structure and links. Run version-helper tests before claiming update and rollback support.

Automated checks do not prove a code interpretation or visual match. Record standards review and rendered visual approval separately.
