"""Deterministic safe 2D compilation, export and revision-bound acceptance."""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import html
import io
import json
import math
import re
import threading
from typing import Any

from .drawing_models import DrawingPlan, DrawingPrimitive, DrawingView, DrawingViewPlan
from .reference_layout import paper_layout, reference_graphics, BLUE, YELLOW, REFERENCE_LAYOUT_VERSION

_FONT_LOCK=threading.Lock()


def _pdf_font(text):
    """Use a standard Chinese CID font without copying proprietary font files."""
    try:text.encode("cp1252");return "Helvetica"
    except UnicodeEncodeError:pass
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    with _FONT_LOCK:
        if "STSong-Light" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light"


def _view(value) -> DrawingView:
    return value if isinstance(value,DrawingView) else DrawingView.model_validate(value)


def drawing_hash(view: DrawingView | dict) -> str:
    content = _view(view).model_dump(exclude={"review_status","review_issues","review_hash"})
    if not content.get("edit_guards"):
        content.pop("edit_guards",None)  # Preserve exact hashes of legacy accepted drawings.
    for key in ('annotation_margin','review_notes','reference_annotations'):
        if not content.get(key):content.pop(key,None)
    if content.get('reference_annotations'):
        # A changed renderer policy requires a fresh check of its actual output.
        # Empty-reference historical drawings retain their exact review hashes.
        content['reference_layout_policy']=REFERENCE_LAYOUT_VERSION
    for primitive in content['primitives']:
        if primitive.get('fill_rgb') is None:primitive.pop('fill_rgb',None)
    def canonical(value):
        if isinstance(value,float) and value.is_integer():return int(value)
        if isinstance(value,list):return [canonical(v) for v in value]
        if isinstance(value,dict):return {k:canonical(v) for k,v in value.items()}
        return value
    return hashlib.sha256(json.dumps(canonical(content),sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()


def stamp_review(view: DrawingView | dict, passed: bool, issues: list[str] | None = None) -> DrawingView:
    result = _view(view).model_copy(deep=True)
    result.review_status = "passed" if passed else "failed"
    result.review_issues = list(issues or [])
    result.review_hash = drawing_hash(result)
    return result


def _matches(rule, item, width, height):
    if rule.primitive_ids:
        return item.id in rule.primitive_ids or item.source_id in rule.primitive_ids
    if rule.kind is not None and item.kind != rule.kind:
        return False
    if rule.source_kind is not None:
        match=re.match(r"^P\d+-([LRC])\d+$",item.source_id)
        if match is None or {"L":"line","R":"rect","C":"curve"}[match.group(1)]!=rule.source_kind:
            return False
    if rule.style_id is not None and item.source_style_id != rule.style_id:
        return False
    if rule.region is not None:
        box=[v/(width if i%2==0 else height) for i,v in enumerate(item.bbox)]
        region=rule.region
        if rule.region_match == "contained":
            selected=region[0]<=box[0] and region[1]<=box[1] and box[2]<=region[2] and box[3]<=region[3]
        elif rule.region_match == "intersects":
            selected=box[0]<=region[2] and region[0]<=box[2] and box[1]<=region[3] and region[1]<=box[3]
        else:
            x=(box[0]+box[2])/2;y=(box[1]+box[3])/2
            selected=region[0]<=x<=region[2] and region[1]<=y<=region[3]
        if not selected:
            return False
    return True


def _coalesce(primitives: list[DrawingPrimitive]) -> list[DrawingPrimitive]:
    """Coalesce unfilled stroke commands, retaining every original source ID.

    Native paint-order-sensitive filled shapes and all text remain independent.
    Only contiguous unfilled runs are combined; a fill flushes the run first.
    """
    result, groups = [], {}

    def flush():
        result.extend(groups.values()); groups.clear()

    for primitive in primitives:
        if primitive.kind != "path" or primitive.fill != "none" or primitive.stroke_color=="white":
            flush(); result.append(primitive); continue
        clips_key=tuple((clip.fill_rule,tuple((c.op,tuple(c.points)) for c in clip.commands)) for clip in primitive.clips)
        key=(primitive.owner_id,primitive.role,primitive.source_style_id,primitive.stroke_width,primitive.stroke,tuple(primitive.dash),clips_key)
        grouped=groups.get(key)
        if grouped is not None and (len(grouped.commands)+len(primitive.commands)>4000 or len(grouped.source_ids)>=1000):
            result.append(grouped); groups.pop(key); grouped=None
        if grouped is None:
            grouped=primitive.model_copy(deep=True)
            grouped.source_ids=list(primitive.source_ids or [primitive.source_id])
            grouped.id="B_"+primitive.id
            groups[key]=grouped
        else:
            grouped.commands.extend(primitive.commands)
            grouped.source_ids.extend(primitive.source_ids or [primitive.source_id])
            grouped.bbox=[min(grouped.bbox[0],primitive.bbox[0]),min(grouped.bbox[1],primitive.bbox[1]),
                          max(grouped.bbox[2],primitive.bbox[2]),max(grouped.bbox[3],primitive.bbox[3])]
    flush()
    return result


def compile_drawings(inventory: dict, plan: DrawingPlan | dict, parameter_snapshot: dict[str,float | None] | None = None) -> list[DrawingView]:
    """Apply sparse decisions to immutable native inventory, never fabricate paths."""
    plan=plan if isinstance(plan,DrawingPlan) else DrawingPlan.model_validate(plan)
    sources={v["id"]:v for v in inventory.get("views",[])}
    decisions={v.view_id:v for v in plan.views}
    if len(decisions)!=len(plan.views) or set(decisions)-set(sources):
        raise ValueError("Drawing plan contains duplicate or unavailable source views")
    output=[]
    for ident,record in sources.items():
        decision=decisions.get(ident)
        pending=list(record.get("pending",[]))
        if decision is None:
            decision=DrawingViewPlan(view_id=ident)
            pending.append("This required source view has no drawing classification plan.")
        if decision.source_region is not None and any(abs(a-b)>1e-8 for a,b in zip(decision.source_region,record["region"])):
            raise ValueError("Rebuild the native inventory after changing a source region")
        native=[DrawingPrimitive.model_validate(p) for p in record["primitives"]]
        source_ids={p.id for p in native}|{p.source_id for p in native}
        text_aliases=Counter(p.source_id for p in native if p.kind=="text")
        for guard in decision.edit_guards:
            if set(guard.source_primitive_ids)-source_ids:
                raise ValueError("An edit guard cites unavailable native shared-boundary evidence")
        for rule in decision.rules:
            unavailable=sorted(set(rule.primitive_ids)-source_ids)
            if unavailable:
                raise ValueError(f"A drawing rule refers to an unavailable source primitive in view {ident}: {', '.join(unavailable[:5])}")
            if rule.style_id is not None and rule.style_id not in {p.source_style_id for p in native}:
                raise ValueError(f"A drawing rule refers to an unavailable source style in view {ident}: {rule.style_id}")
            text_adjustment=bool(rule.text_fragments) or any(value is not None for value in (rule.text_override,rule.text_offset,rule.font_size,rule.text_length))
            if text_adjustment and any(text_aliases[source_id]>1 for source_id in rule.primitive_ids):
                raise ValueError("A logical source word has multiple native paint runs; select one explicit run ID for a text correction")
        selected=[]
        for item in native:
            include=decision.default_include
            item=item.model_copy(deep=True); item.owner_id=decision.default_owner_id
            fragments=[]
            for rule in decision.rules:
                if not _matches(rule,item,record["width"],record["height"]):
                    continue
                if rule.include is not None:
                    include=rule.include
                if rule.role is not None:
                    item.role=rule.role
                if rule.owner_id is not None:
                    item.owner_id=rule.owner_id
                text_adjustment=bool(rule.text_fragments) or any(value is not None for value in (rule.text_override,rule.text_offset,rule.font_size,rule.text_length))
                if text_adjustment:
                    if item.kind != "text":
                        raise ValueError("A source text correction cannot change a physical path")
                    if rule.text_override is not None:
                        fragments=[]
                    elif rule.text_fragments:
                        fragments=list(rule.text_fragments)
                    changed_text=rule.text_override is not None and rule.text_override!=item.text
                    if changed_text:item.text=rule.text_override;item.text_length=None
                    if rule.text_offset is not None:
                        dx,dy=rule.text_offset;item.x+=dx;item.y+=dy
                        item.bbox=[value+(dx if index%2==0 else dy) for index,value in enumerate(item.bbox)]
                    if rule.font_size is not None:item.font_size=rule.font_size
                    if rule.text_length is not None:item.text_length=rule.text_length
                    if changed_text or rule.font_size is not None or rule.text_length is not None:
                        from reportlab.pdfbase.pdfmetrics import stringWidth
                        length=item.text_length if item.text_length is not None else stringWidth(item.text,_pdf_font(item.text),item.font_size)
                        angle=math.radians(item.rotation)
                        w=abs(length*math.cos(angle))+abs(item.font_size*math.sin(angle))
                        h=abs(length*math.sin(angle))+abs(item.font_size*math.cos(angle))
                        item.bbox=[item.x-w/2,item.y-h/2,item.x+w/2,item.y+h/2]
            if include:
                if item.kind=="text" and not fragments and "\ufffd" in item.text:
                    pending.append(f"Unmapped source glyph in {item.source_id}: verify the label against the source image.")
                if fragments:
                    from reportlab.pdfbase.pdfmetrics import stringWidth
                    for ordinal,fragment in enumerate(fragments):
                        child=item.model_copy(deep=True)
                        child.id=item.id+f"_FRAGMENT_{ordinal+1}"
                        child.text=fragment.text
                        child.x+=fragment.offset[0];child.y+=fragment.offset[1]
                        child.font_size=fragment.font_size or item.font_size
                        child.text_length=fragment.text_length
                        span=child.text_length or stringWidth(child.text,_pdf_font(child.text),child.font_size)
                        angle=math.radians(child.rotation)
                        half_width=(abs(math.cos(angle))*span+abs(math.sin(angle))*child.font_size)/2
                        half_height=(abs(math.sin(angle))*span+abs(math.cos(angle))*child.font_size)/2
                        child.bbox=[child.x-half_width,child.y-half_height,child.x+half_width,child.y+half_height]
                        if '\ufffd' in child.text:
                            pending.append(f"Unmapped source glyph in {item.source_id}: verify the label against the source image.")
                        selected.append(child)
                else:
                    selected.append(item)
        pending.extend(decision.pending)
        output.append(DrawingView(id=ident,label=record["label"],kind=record["kind"],
            owner_ids=sorted({p.owner_id for p in selected}),document_id=record["document_id"],page=record["page"],
            region=record["region"],source_sha256=record["source_sha256"],width=record["width"],height=record["height"],
            primitives=_coalesce(selected),pending=list(dict.fromkeys(pending)),parameter_snapshot=parameter_snapshot or {},
            edit_guards=[guard.model_copy(deep=True) for guard in decision.edit_guards]))
    return output


def _has_fill_area(primitive):
    """Reject zero-area fill paths, including retraced/even-odd empty contours."""
    segments=[];current=None;start=None
    def edge(first,second):
        if first is not None and first!=second:segments.append((first,second))
    for command in primitive.commands:
        points=command.points
        if command.op=="M":
            edge(current,start);current=tuple(points);start=current
        elif command.op=="L":
            point=tuple(points);edge(current,point);current=point
        elif command.op=="C" and current is not None:
            a=current;b=points[:2];c=points[2:4];d=points[4:]
            for step in range(1,17):
                t=step/16;s=1-t
                point=tuple(s*s*s*a[i]+3*s*s*t*b[i]+3*s*t*t*c[i]+t*t*t*d[i] for i in (0,1))
                edge(current,point);current=point
        elif command.op=="Z":edge(current,start);current=start
    edge(current,start)
    vertical=[(a,b) for a,b in segments if abs(a[1]-b[1])>1e-9]
    levels=sorted({point[1] for pair in vertical for point in pair})
    for low,high in zip(levels,levels[1:]):
        if high-low<1e-9:continue
        # A self-intersecting contour can cross at the exact midpoint. Two
        # interior scanlines retain valid bow-ties while rejecting retraces.
        for fraction in (.38196601125,.61803398875):
            y=low+(high-low)*fraction;intersections=[]
            for a,b in vertical:
                if min(a[1],b[1])<y<max(a[1],b[1]):
                    x=a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1])
                    intersections.append((x,1 if b[1]>a[1] else -1))
            intersections.sort();winding=0;parity=0;previous=None;index=0
            while index<len(intersections):
                x=intersections[index][0]
                inside=bool(parity) if primitive.fill_rule=="evenodd" else winding!=0
                if previous is not None and x-previous>1e-7 and inside:return True
                count=0;change=0
                while index<len(intersections) and abs(intersections[index][0]-x)<1e-9:
                    count+=1;change+=intersections[index][1];index+=1
                winding+=change;parity=(parity+count)%2;previous=x
    return False


def _object_geometry(primitive):
    return (primitive.kind=="path" and primitive.role in ("geometry","context") and len(primitive.commands)>1
            and ((primitive.stroke and primitive.stroke_color!="white") or (primitive.fill=="black" and _has_fill_area(primitive))))


def _counts(view):
    result=Counter()
    for p in view.primitives:
        if p.role == "texture":
            continue
        n=len(p.source_ids) or 1
        if _object_geometry(p):
            result["geometry"]+=n
        if p.role=="dimension":result["dimension"]+=n
        if p.role=="opening":result["symbol"]+=n
    return result


def assess_drawings(drawings, current_resolved: dict | None = None, expected_views: list | None = None) -> dict:
    """Require useful visible geometry and a matching independent review hash."""
    records=[];issues=[]
    supplied={_view(v).id:_view(v) for v in drawings}
    expected=[]
    for item in expected_views or []:
        expected.append(item if isinstance(item,str) else item.get("id") if isinstance(item,dict) else item.id)
    for ident in [*supplied,*[x for x in expected if x not in supplied]]:
        view=supplied.get(ident)
        if view is None:
            records.append({"id":ident,"label":ident,"kind":"plan","status":"incomplete","issues":["Required source drawing is missing."],
                            "geometry_count":0,"dimension_count":0,"symbol_count":0,"review_status":"pending","content_hash":None})
            continue
        counts=_counts(view); problems=list(view.pending); state="ready"
        geometric=[p for p in view.primitives if _object_geometry(p)]
        visible=[p for p in geometric if p.bbox[2]>=0 and p.bbox[0]<=view.width and p.bbox[3]>=0 and p.bbox[1]<=view.height]
        if not visible:
            problems.append("This required view contains no visible object geometry.")
        elif max(p.bbox[2] for p in visible)-min(p.bbox[0] for p in visible)<.1 or max(p.bbox[3] for p in visible)-min(p.bbox[1] for p in visible)<.1:
            problems.append("Object geometry collapses to a line in this view.")
        if problems:state="incomplete"
        changed=[]
        if current_resolved is not None:
            for key,baseline in view.parameter_snapshot.items():
                current=current_resolved.get(key)
                if (current is None)!=(baseline is None) or (current is not None and baseline is not None and abs(current-baseline)>1e-6):
                    changed.append(key)
        if changed:
            state="stale";problems.append("Source drawing needs regeneration after parameter changes: "+", ".join(changed[:15]))
        content_hash=drawing_hash(view)
        if state=="ready" and (view.review_status!="passed" or view.review_hash!=content_hash):
            state="needs_review"
            problems.extend(view.review_issues or ["Independent rendered drawing review is pending."])
            if view.review_hash is not None and view.review_hash!=content_hash:
                problems.append("The recorded review belongs to different drawing content.")
        records.append({"id":view.id,"label":view.label,"kind":view.kind,"status":state,"issues":list(dict.fromkeys(problems)),
            "geometry_count":counts["geometry"],"dimension_count":counts["dimension"],"symbol_count":counts["symbol"],
            "review_status":view.review_status,"content_hash":content_hash})
    priority={"ready":0,"needs_review":1,"stale":2,"incomplete":3}
    status=max((r["status"] for r in records),key=lambda x:priority[x],default="incomplete")
    if not records:issues.append("No source-based drawings have been generated.")
    issues.extend(f"{r['label']}: {issue}" for r in records for issue in r["issues"])
    return {"status":status,"views":records,"issues":issues}


def _number(value):
    return f"{value:.5f}".rstrip("0").rstrip(".") or "0"


def _ink(primitive):
    return "#2563eb" if primitive.role=="dimension" else "#000000"


def _svg_path(commands):
    return " ".join(c.op+(" "+" ".join(_number(n) for n in c.points) if c.points else "") for c in commands)


def _pdf_path(canvas,commands):
    shape=canvas.beginPath()
    for cmd in commands:
        pts=cmd.points
        if cmd.op=="M":shape.moveTo(pts[0],-pts[1])
        elif cmd.op=="L":shape.lineTo(pts[0],-pts[1])
        elif cmd.op=="C":shape.curveTo(pts[0],-pts[1],pts[2],-pts[3],pts[4],-pts[5])
        else:shape.close()
    return shape


def _review_note_layout(view):
    """Wrap declared source-review notes outside native geometry, never truncate."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    if view.reference_annotations or not view.review_notes:return [],0
    lines=[];width=max(16.,view.width)
    for note in view.review_notes:
        font=_pdf_font(note);line='-'
        for word in note.split():
            if stringWidth(line+' '+word,font,8)<=width:line+=' '+word;continue
            if line!='-':lines.append(line);line=''
            for character in word:
                if line and stringWidth(line+character,font,8)>width:lines.append(line);line=''
                line+=character
        if line:lines.append(line)
    if len(lines)>240:raise ValueError('Source review notes exceed the readable bounded export; reduce the requested source scope.')
    return lines,(len(lines)+1)*11+14


def render_svg(view: DrawingView | dict) -> str:
    from reportlab.pdfbase.pdfmetrics import stringWidth
    view=_view(view);esc=lambda s:html.escape(str(s),quote=True)
    notes,note_height=_review_note_layout(view)
    layout=paper_layout(view,note_height);pad,title=layout['origin'];width,height=layout['width'],layout['height']
    title_size=min(12,view.width/max(1,stringWidth(view.label,_pdf_font(view.label),1)))
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_number(width)} {_number(height)}" role="img" aria-label="{esc(view.label)} source-based drawing">',
           f'<rect width="{_number(width)}" height="{_number(height)}" fill="white"/>',
           f'<text x="{pad}" y="20" font-family="Arial,sans-serif" font-size="{_number(title_size)}" fill="#173e37">{esc(view.label)}</text>',
           f'<defs><clipPath id="source-crop"><rect width="{_number(view.width)}" height="{_number(view.height)}"/></clipPath></defs>',
           f'<defs><clipPath id="source-annotation-margin"><rect x="{_number(-view.annotation_margin)}" width="{_number(view.width+2*view.annotation_margin)}" height="{_number(view.height)}"/></clipPath></defs>' if view.annotation_margin else '',
           f'<g transform="translate({pad} {title})"'+('>' if view.annotation_margin else ' clip-path="url(#source-crop)">')]
    clip_defs={}
    for p in view.primitives:
        for clip in p.clips:
            identity=json.dumps(clip.model_dump(),sort_keys=True)
            if identity not in clip_defs:
                name="native-clip-"+str(len(clip_defs))
                clip_defs[identity]=name
                parts.append(f'<defs><clipPath id="{name}"><path d="{_svg_path(clip.commands)}" clip-rule="{clip.fill_rule}"/></clipPath></defs>')
    for p in view.primitives:
        if p.role=="texture":continue
        if view.annotation_margin:
            outer='source-annotation-margin' if p.kind=='text' else 'source-crop'
            parts.append(f'<g clip-path="url(#{outer})">')
        for clip in p.clips:
            name=clip_defs[json.dumps(clip.model_dump(),sort_keys=True)]
            parts.append(f'<g clip-path="url(#{name})">')
        common=f'data-object-id="{esc(p.owner_id)}" data-source-id="{esc(p.source_id)}" data-role="{p.role}"'
        if p.source_ids:common+=f' data-source-count="{len(p.source_ids)}" data-source-ids="{esc(" ".join(p.source_ids))}"'
        ink=_ink(p)
        if p.kind=="path":
            d=_svg_path(p.commands)
            fill="white" if p.fill=="white" else (p.fill_rgb or ink) if p.fill=="black" else "none"
            dash=f' stroke-dasharray="{" ".join(_number(x) for x in p.dash)}"' if p.dash else ""
            stroke="none" if not p.stroke else "white" if p.stroke_color=="white" else ink
            parts.append(f'<path {common} d="{d}" fill="{fill}" fill-rule="{p.fill_rule}" stroke="{stroke}" stroke-width="{_number(p.stroke_width)}" stroke-linejoin="round" stroke-linecap="round"{dash}/>')
        else:
            length=f' textLength="{_number(p.text_length)}" lengthAdjust="spacingAndGlyphs"' if p.text_length else ""
            rotation=f' transform="rotate({_number(p.rotation)} {_number(p.x)} {_number(p.y)})"' if p.rotation else ""
            parts.append(f'<text {common} x="{_number(p.x)}" y="{_number(p.y)}" text-anchor="middle" dominant-baseline="central" font-family="Arial,sans-serif" font-size="{_number(p.font_size)}" fill="{ink}"{length}{rotation}>{esc(p.text)}</text>')
        parts.extend('</g>' for _ in p.clips)
        if view.annotation_margin:parts.append('</g>')
    footer_label="Amended design preview · NTS · canonical model controls physical dimensions" if view.representation=="amended_design" else "Source-based customer review · NTS · original observations retained"
    footer_size=min(9,view.width/max(1,stringWidth(footer_label,"Helvetica",1)))
    parts.append('</g>')
    graphics=reference_graphics(view)
    if graphics['labels']:
        footer_label='Customer review - NTS - yellow values are reference dimensions'
        parts.append(f'<g data-layer="reference-dimensions" transform="translate({pad} {title})">')
        for line in graphics['lines']:
            x1,y1,x2,y2=line['points']
            parts.append(f'<path data-control-id="{esc(line["control_id"])}" data-reference-kind="{line["kind"]}" d="M {_number(x1)} {_number(y1)} L {_number(x2)} {_number(y2)}" stroke="{BLUE}" stroke-width="0.5" fill="none"/>')
        for label in graphics['labels']:
            parts.append(f'<g data-control-id="{esc(label["control_id"])}" data-reference-numeric="{str(label["numeric"]).lower()}" transform="translate({_number(label["x"])} {_number(label["y"])}) rotate({_number(label["rotation"])})">')
            if label['numeric']:
                parts.append(f'<rect x="{_number(-label["width"]/2-3)}" y="{_number(-label["font"]/2-2)}" width="{_number(label["width"]+6)}" height="{_number(label["font"]+4)}" fill="{YELLOW}"/>')
            parts.append(f'<text text-anchor="middle" dominant-baseline="central" font-family="Arial,sans-serif" font-size="{label["font"]}" fill="{BLUE if label["numeric"] else "#000000"}">{esc(label["text"])}</text></g>')
        parts.append('</g>')
    if notes:
        y=title+view.height+layout['reference_height']+20
        parts.append(f'<text x="{pad}" y="{_number(y)}" font-family="Arial,sans-serif" font-size="8" fill="#536b64">Review notes - unresolved source observations</text>')
        for line in notes:
            y+=11;parts.append(f'<text x="{pad}" y="{_number(y)}" font-family="Arial,sans-serif" font-size="8" fill="#536b64">{esc(line)}</text>')
    footer_size=min(9,(width-48)/max(1,stringWidth(footer_label,'Helvetica',1)))
    parts.extend([f'<text x="{pad}" y="{_number(height-10)}" font-family="Arial,sans-serif" font-size="{_number(footer_size)}" fill="#536b64">{footer_label}</text>','</svg>'])
    return "".join(parts)


def render_pdf(view: DrawingView | dict, *, owner_colors: dict[str, str] | None = None) -> bytes:
    """Emit actual vector geometry with the same native display-list records."""
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import HexColor
    from reportlab.pdfbase.pdfmetrics import stringWidth
    view=_view(view);notes,note_height=_review_note_layout(view)
    layout=paper_layout(view,note_height);pad,title=layout['origin'];width,height=layout['width'],layout['height']
    output=io.BytesIO();c=canvas.Canvas(output,pagesize=(width,height),invariant=1,pageCompression=1)
    title_font=_pdf_font(view.label);title_size=min(12,view.width/max(1,stringWidth(view.label,title_font,1)))
    c.setTitle(view.label);c.setFont(title_font,title_size);c.setFillColor(HexColor("#173e37"));c.drawString(pad,height-20,view.label)
    c.saveState();c.translate(pad,height-title)
    if not view.annotation_margin:
        clip=c.beginPath();clip.rect(0,-view.height,view.width,view.height);c.clipPath(clip,stroke=0,fill=0)
    for p in view.primitives:
        if p.role=="texture":continue
        c.saveState()
        if view.annotation_margin:
            margin=view.annotation_margin if p.kind=='text' else 0
            clip=c.beginPath();clip.rect(-margin,-view.height,view.width+2*margin,view.height);c.clipPath(clip,stroke=0,fill=0)
        for clip in p.clips:c.clipPath(_pdf_path(c,clip.commands),stroke=0,fill=0,fillMode=0 if clip.fill_rule=="evenodd" else 1)
        ink=HexColor(owner_colors.get(p.owner_id, _ink(p)) if owner_colors else _ink(p));c.setStrokeColor(ink);c.setFillColor(ink)
        if p.kind=="path":
            shape=_pdf_path(c,p.commands)
            c.setLineWidth(p.stroke_width);c.setLineJoin(1);c.setLineCap(1);c.setDash(p.dash)
            if p.fill=="white":c.setFillColor(HexColor("#ffffff"))
            elif p.fill=="black" and p.fill_rgb:c.setFillColor(HexColor(p.fill_rgb))
            if p.stroke_color=="white":c.setStrokeColor(HexColor("#ffffff"))
            c.drawPath(shape,stroke=int(p.stroke),fill=int(p.fill!="none"),fillMode=0 if p.fill_rule=="evenodd" else 1)
        else:
            c.saveState();c.translate(p.x,-p.y);c.rotate(-p.rotation);font=_pdf_font(p.text);c.setFont(font,p.font_size)
            native_width=c.stringWidth(p.text,font,p.font_size)
            if p.text_length and native_width>0:c.scale(p.text_length/native_width,1)
            c.drawCentredString(0,-p.font_size*.35,p.text);c.restoreState()
        c.restoreState()
    footer_label="Amended design preview - NTS - canonical model controls physical dimensions" if view.representation=="amended_design" else "Source-based customer review - NTS - original observations retained"
    footer_size=min(9,view.width/max(1,stringWidth(footer_label,"Helvetica",1)))
    c.restoreState()
    graphics=reference_graphics(view)
    if graphics['labels']:
        footer_label='Customer review - NTS - yellow values are reference dimensions'
        c.saveState();c.translate(pad,height-title);c.setStrokeColor(HexColor(BLUE));c.setLineWidth(.5);c.setDash([])
        for line in graphics['lines']:
            x1,y1,x2,y2=line['points'];c.line(x1,-y1,x2,-y2)
        for label in graphics['labels']:
            c.saveState();c.translate(label['x'],-label['y']);c.rotate(-label['rotation'])
            if label['numeric']:
                c.setFillColor(HexColor(YELLOW));c.rect(-label['width']/2-3,-label['font']/2-2,label['width']+6,label['font']+4,stroke=0,fill=1)
            c.setFillColor(HexColor(BLUE if label['numeric'] else '#000000'));c.setFont('Helvetica',label['font'])
            c.drawCentredString(0,-label['font']*.35,label['text']);c.restoreState()
        c.restoreState()
    if notes:
        y=height-title-view.height-layout['reference_height']-20;c.setFillColor(HexColor('#536b64'));c.setFont('Helvetica',8)
        c.drawString(pad,y,'Review notes - unresolved source observations')
        for line in notes:
            y-=11;c.setFont(_pdf_font(line),8);c.drawString(pad,y,line)
    footer_size=min(9,(width-48)/max(1,stringWidth(footer_label,'Helvetica',1)))
    c.setFont("Helvetica",footer_size);c.setFillColor(HexColor("#536b64"));c.drawString(pad,10,footer_label)
    c.showPage();c.save();return output.getvalue()


def render_png(view: DrawingView | dict, max_size: int = 1600, *, owner_colors: dict[str, str] | None = None) -> bytes:
    import pypdfium2 as pdfium
    from .documents import _PDF_RENDER_LOCK
    if not 100<=max_size<=5000:raise ValueError("Invalid drawing preview size")
    with _PDF_RENDER_LOCK, pdfium.PdfDocument(render_pdf(view, owner_colors=owner_colors)) as document:
        page=document[0]
        try:
            bitmap=page.render(scale=min(3,max_size/max(page.get_size())))
            try:
                output=io.BytesIO();bitmap.to_pil().save(output,format="PNG");return output.getvalue()
            finally:bitmap.close()
        finally:page.close()


def render_owner_map(view: DrawingView | dict, max_size: int = 1200) -> tuple[bytes, dict[str, str]]:
    """Inspection-only ink colors expose actual edit ownership, retaining all masks.

    The model and normal customer exports are unchanged. The adjacent legend is
    required because these colors identify owners rather than physical materials.
    """
    import colorsys
    view = _view(view)
    owners = sorted({p.owner_id for p in view.primitives if p.role != 'texture' and
        (p.kind == 'text' or (p.stroke and p.stroke_color == 'ink') or p.fill == 'black')})
    palette = ['#1565c0','#c62828','#2e7d32','#7b1fa2','#e65100','#00838f',
               '#6d4c41','#ad1457','#455a64','#827717','#4527a0','#00695c']
    colors = {}
    for index, owner in enumerate(owners):
        if index < len(palette):
            color = palette[index]
        else:
            rgb = colorsys.hsv_to_rgb((index*.61803398875)%1, .78, .65)
            color = '#'+''.join(f'{round(value*255):02x}' for value in rgb)
        colors[owner] = color
    return render_png(view, max_size=max_size, owner_colors=colors), colors
