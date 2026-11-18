"""Reconcile selection references only when an intentional source crop changes."""
from __future__ import annotations


def reconcile_cropped_selectors(plan, previous_inventory, current_inventory):
    """Drop only verified old references now wholly outside the new source crop.

    Empty ID lists must never accidentally become wildcard rules. Unknown IDs,
    source changes and extraction drift without a crop change still reject. No
    review status is transferred; the new cropped drawing needs rendered review.
    The source inventories are immutable, and plan changes commit atomically.
    """
    before={v['id']:v for v in previous_inventory['views']}
    after={v['id']:v for v in current_inventory['views']}
    if set(before)!=set(after):
        raise ValueError('A source crop cannot change the required view identities')
    updated=plan.model_copy(deep=True)
    reports=[]
    for decision in updated.views:
        old=before[decision.view_id];new=after[decision.view_id]
        if any(old.get(k)!=new.get(k) for k in ('document_id','source_sha256','page','kind')):
            raise ValueError('A source crop cannot change source identity')
        old_ids={p.get(k) for p in old['primitives'] for k in ('id','source_id') if p.get(k)}
        new_ids={p.get(k) for p in new['primitives'] for k in ('id','source_id') if p.get(k)}
        old_styles={p.get('source_style_id') for p in old['primitives']}
        new_styles={p.get('source_style_id') for p in new['primitives']}
        cropped=old['region']!=new['region']
        if any(set(guard.source_primitive_ids)-new_ids for guard in decision.edit_guards):
            raise ValueError('A source crop would discard shared-boundary edit guard evidence')
        def outside_new_crop(primitive):
            # Native boxes are crop-local PDF points. Convert to normalized page
            # coordinates before proving a missing object really left the crop.
            region=old['region'];box=primitive.get('bbox')
            if not box or old.get('width',0)<=0 or old.get('height',0)<=0:
                return False
            full=[region[i%2]+box[i]/old['width' if i%2==0 else 'height']*
                  (region[i%2+2]-region[i%2]) for i in range(4)]
            target=new['region']
            return full[2]<target[0] or full[0]>target[2] or full[3]<target[1] or full[1]>target[3]
        old_by_id={p.get(k):p for p in old['primitives'] for k in ('id','source_id') if p.get(k)}
        retained=[];removed_ids=set();removed_styles=set()
        for rule in decision.rules:
            missing=set(rule.primitive_ids)-new_ids
            if missing and (not cropped or missing-old_ids):
                raise ValueError('A crop rule references unverified source primitives')
            if any(not outside_new_crop(old_by_id[ident]) for ident in missing):
                raise ValueError('A missing source primitive still intersects the changed crop')
            if rule.primitive_ids:
                removed_ids.update(missing)
                rule.primitive_ids=[ident for ident in rule.primitive_ids if ident in new_ids]
                if not rule.primitive_ids:
                    continue  # Never turn a vacuous exact-ID selection into a wildcard.
            if rule.style_id is not None and rule.style_id not in new_styles:
                if not cropped or rule.style_id not in old_styles:
                    raise ValueError('A crop rule references an unverified source style')
                if any(not outside_new_crop(p) for p in old['primitives'] if p.get('source_style_id')==rule.style_id):
                    raise ValueError('A missing source style still intersects the changed crop')
                removed_styles.add(rule.style_id)
                if rule.primitive_ids:
                    # IDs have precedence over styles; this predicate was unused.
                    rule.style_id=None
                else:
                    continue
            retained.append(rule)
        decision.rules=retained
        if removed_ids or removed_styles:
            reports.append({'view_id':decision.view_id,'previous_region':old['region'],
                'region':new['region'],'removed_id_count':len(removed_ids),
                'removed_ids_sample':sorted(removed_ids)[:50],
                'removed_styles':sorted(removed_styles),
                'review_required':True})
    plan.views=updated.views
    return reports
