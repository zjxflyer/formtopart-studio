"""Read native PDF appearance in displayed, rotated page coordinates.

This is an evidence inventory, not a CAD dimension solver. Native point distances
are never promoted to millimetres or used to fill an unknown construction value.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from .drawing_models import DrawingPrimitive, PathCommand, DrawingClip

MAX_PAGE_PRIMITIVES = 300000
MAX_VIEW_PRIMITIVES = 60000
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024


def _color(value):
    if isinstance(value, (int, float)):
        values = [value] * 3
    elif isinstance(value, (tuple, list)) and len(value) == 3:
        values = value
    elif isinstance(value, (tuple, list)) and len(value) == 4:
        c, m, y, k = value
        values = [1-min(1,c+k), 1-min(1,m+k), 1-min(1,y+k)]
    else:
        values = [0, 0, 0]
    return "#" + "".join(f"{max(0,min(255,round(float(x)*255))):02x}" for x in values)


def _style(item, kind):
    dash = item.get("dash")
    dash = dash[0] if isinstance(dash, (tuple, list)) and len(dash) == 2 and isinstance(dash[0], (tuple, list)) else []
    record = {"kind": kind, "color": _color(item.get("stroking_color") if kind == "path" else item.get("non_stroking_color")),
              "width": round(float(item.get("linewidth", .5)), 3), "dash": [round(float(x),3) for x in dash]}
    if kind=="path":record.update(stroke=bool(item.get("stroke",True)),fill=bool(item.get("fill")),
                                   fill_color=_color(item.get("non_stroking_color")),fill_rule="evenodd" if item.get("evenodd") else "nonzero")
    identity = "S_" + hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()[:12]
    return identity, record


def _bbox(item):
    return [float(item["x0"]), float(item["top"]), float(item["x1"]), float(item["bottom"])]


def _intersects(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _native_commands(item, dx, dy):
    """pdfplumber's path and pts already use top-left display coordinates."""
    commands, current = [], None
    for entry in item.get("path", []):
        op = entry[0]
        points = [[float(p[0])-dx, float(p[1])-dy] for p in entry[1:] if isinstance(p,(tuple,list)) and len(p)==2]
        if op == "m" and points:
            current = points[0]; commands.append(PathCommand(op="M",points=current))
        elif op == "l" and points:
            current = points[0]; commands.append(PathCommand(op="L",points=current))
        elif op == "c" and len(points) == 3:
            commands.append(PathCommand(op="C",points=[x for p in points for x in p])); current=points[-1]
        elif op == "v" and len(points) == 2 and current is not None:
            commands.append(PathCommand(op="C",points=[*current,*points[0],*points[1]])); current=points[-1]
        elif op == "y" and len(points) == 2:
            commands.append(PathCommand(op="C",points=[*points[0],*points[1],*points[1]])); current=points[-1]
        elif op in ("h", "z"):
            commands.append(PathCommand(op="Z"))
    if not commands:
        points = item.get("pts") or [(item["x0"],item["top"]),(item["x1"],item["bottom"])]
        commands = [PathCommand(op="M" if i == 0 else "L",points=[float(p[0])-dx,float(p[1])-dy]) for i,p in enumerate(points)]
        if item.get("object_type") == "rect":
            # Rectangle pts are not guaranteed to repeat their first endpoint.
            commands.append(PathCommand(op="Z"))
    return commands


def _default_text_role(text):
    if re.search(r"\b(?:WD|ST|TL|PT|PL|MT|GL)\d*\b|FINISH", text, re.I):
        return "material"
    if re.search(r"[\d].*[\"'′″]|\d+\s*/\s*\d+", text):
        return "dimension"
    return "context"


def _source_kind(source_id):
    match=re.match(r"^P\d+-([LRC])\d+$",source_id)
    return {"L":"line","R":"rect","C":"curve"}[match.group(1)] if match else None


def _view_record(view):
    return view.model_dump() if hasattr(view, "model_dump") else dict(view)


def _char_key(char):
    return (char.get("text"),char.get("fontname"),*(round(float(char.get(k,0)),6) for k in ("x0","top","x1","bottom")))


def _native_layout(page):
    """Retain PDF compound fills and clipping that pdfminer's default loses."""
    from pdfplumber.page import PDFPageAggregatorWithMarkedContent
    from pdfminer.pdfinterp import PDFPageInterpreter
    from pdfminer.layout import LTCurve
    from pdfminer.utils import apply_matrix_pt

    def transformed(path,ctm):
        return [(entry[0],*[apply_matrix_pt(ctm,(float(x),float(y))) for x,y in zip(entry[1::2],entry[2::2])]) for entry in path]

    class NativeAggregator(PDFPageAggregatorWithMarkedContent):
        clips=[]
        pending_clip=None

        def paint_path(self,gstate,stroke,fill,evenodd,path):
            before=len(self.cur_item._objs)
            if fill and sum(entry[0]=="m" for entry in path)>1:
                actual=transformed(path,self.ctm)
                points=[point for entry in actual for point in entry[1:]]
                if points:
                    self.cur_item.add(LTCurve(gstate.linewidth,points,stroke,fill,evenodd,gstate.scolor,gstate.ncolor,
                                             original_path=actual,dashing_style=gstate.dash))
                    self.tag_cur_item()
            else:
                super().paint_path(gstate,stroke,fill,evenodd,path)
            for obj in self.cur_item._objs[before:]:obj.vwc_clips=self.clips
            if self.pending_clip is not None:
                self.clips=[*self.clips,self.pending_clip];self.pending_clip=None

        def render_char(self,*args,**kwargs):
            advance=super().render_char(*args,**kwargs)
            if self.cur_item._objs:
                obj=self.cur_item._objs[-1];obj.vwc_clips=self.clips
                matrix=args[0];obj.vwc_font_size=abs(float(args[2]))*math.hypot(matrix[2],matrix[3])
            return advance

    class NativeInterpreter(PDFPageInterpreter):
        def init_state(self,ctm):
            super().init_state(ctm);self.clip_stack=[]
            self.graphicstate.linewidth=1.  # PDF initial graphics state, before any w operator

        def do_q(self):
            self.clip_stack.append(self.device.clips);super().do_q()

        def do_Q(self):
            super().do_Q()
            if self.clip_stack:self.device.clips=self.clip_stack.pop()

        def do_W(self):
            self.device.pending_clip={"path":transformed(self.curpath,self.ctm),"fill_rule":"nonzero"}

        def do_W_a(self):
            self.device.pending_clip={"path":transformed(self.curpath,self.ctm),"fill_rule":"evenodd"}

        def do_n(self):
            if self.device.pending_clip is not None:
                self.device.clips=[*self.device.clips,self.device.pending_clip];self.device.pending_clip=None
            super().do_n()

        def do_Do(self,xobjid_arg):
            saved=self.device.clips
            try:super().do_Do(xobjid_arg)
            finally:self.device.clips=saved

    device=NativeAggregator(page.pdf.rsrcmgr,pageno=page.page_number,laparams=None)
    NativeInterpreter(page.pdf.rsrcmgr,device).process_page(page.page_obj)
    page._layout=device.get_result()


def _ordered_native(page, number):
    """Retain graphics paint order instead of regrouping lines/rects/curves.

    With the default (no LAParams) pdfminer layout children follow paint order.
    Populate pdfplumber's same object cache once so word extraction reuses chars.
    Source IDs remain per-kind ordinals, independent of selected crop and order.
    """
    kinds={"line":"L","rect":"R","curve":"C"}
    counts=Counter();native=[];chars={};objects=defaultdict(list);clip_cache={}
    from pdfminer.layout import LTContainer
    def iterate(raw_objects):
        for obj in raw_objects:
            if isinstance(obj,LTContainer):yield from iterate(obj._objs)
            else:
                item=page.process_object(obj)
                if hasattr(obj,"vwc_font_size"):item["vwc_font_size"]=obj.vwc_font_size
                clips=getattr(obj,"vwc_clips",[]);key=id(clips)
                if key not in clip_cache:clip_cache[key]=[dict(clip,path=[(cmd,*[page.point2coord(p) for p in points]) for cmd,*points in clip["path"]]) for clip in clips]
                item["vwc_clips"]=clip_cache[key]
                yield item
    _native_layout(page)
    for order,item in enumerate(iterate(page.layout._objs)):
        kind=item["object_type"]
        if kind=="anno":continue
        objects[kind].append(item)
        if kind in kinds:
            native.append((f"P{number}-{kinds[kind]}{counts[kind]:06d}",item,order));counts[kind]+=1
        elif kind=="char":
            # Keep the identity on the actual character too: coincident repeated
            # glyphs can share _char_key but were painted at different times.
            item["vwc_paint_order"]=order
            chars.setdefault(_char_key(item),(order,item.get("vwc_clips",[])))
    page._objects=dict(objects)
    return native,chars


def _extract_words(page):
    """Use real character baselines for diagonal labels, rather than horizontal rows."""
    native_chars=page.chars
    normal=[];angled=defaultdict(list)
    for char in native_chars:
        matrix=char.get("matrix",(1,0,0,1,0,0));angle=-math.degrees(math.atan2(matrix[1],matrix[0]))
        if abs(angle/90-round(angle/90))<.0001:normal.append(char);continue
        theta=math.radians(angle);u=(math.cos(theta),math.sin(theta));v=(-u[1],u[0])
        origin=page.point2coord((matrix[4],matrix[5]));center=((char["x0"]+char["x1"])/2,(char["top"]+char["bottom"])/2)
        angled[(round(angle,4),char.get("fontname"))].append((char,origin[0]*u[0]+origin[1]*u[1],origin[0]*v[0]+origin[1]*v[1],center[0]*v[0]+center[1]*v[1]))
    page._objects["char"]=normal
    try:words=page.extract_words(x_tolerance=1.5,y_tolerance=2,line_dir_rotated="rtl",char_dir_rotated="btt",return_chars=True)
    finally:page._objects["char"]=native_chars
    for (angle,font),items in angled.items():
        clusters=[]
        for item in sorted(items,key=lambda x:x[2]):
            size=item[0].get("vwc_font_size",item[0]["size"])
            cluster=next((c for c in reversed(clusters) if abs(c[0][2]-item[2])<max(.4,size*.18)),None)
            if cluster is None:clusters.append([item])
            else:cluster.append(item)
        for cluster in clusters:
            ordered=sorted(cluster,key=lambda x:x[1]);runs=[]
            for item in ordered:
                size=item[0].get("vwc_font_size",item[0]["size"])
                if not runs or item[1]-runs[-1][-1][1]>size*1.5:runs.append([item])
                else:runs[-1].append(item)
            for run in runs:
                chars=[item[0] for item in run];text="".join(char["text"] for char in chars).strip()
                if not text:continue
                size=sum(char.get("vwc_font_size",char["size"]) for char in chars)/len(chars)
                steps=[b[1]-a[1] for a,b in zip(run,run[1:]) if b[1]-a[1]>.001]
                last_width=abs(chars[-1].get("adv",0))*math.hypot(*chars[-1]["matrix"][:2])
                if last_width<.001:last_width=sorted(steps)[len(steps)//2] if steps else size*.5
                length=run[-1][1]-run[0][1]+last_width;along=(run[0][1]+run[-1][1]+last_width)/2
                across=sum(item[3] for item in run)/len(run);theta=math.radians(angle);u=(math.cos(theta),math.sin(theta));v=(-u[1],u[0])
                words.append(dict(text=text,chars=chars,upright=True,x0=min(c["x0"] for c in chars),x1=max(c["x1"] for c in chars),top=min(c["top"] for c in chars),bottom=max(c["bottom"] for c in chars),
                                  _angle=angle,_font_size=size,_text_length=length,_x=along*u[0]+across*v[0],_y=along*u[1]+across*v[1]))
    return words


def _word_paint_runs(word, char_order, fallback_order):
    """Partition logical reading order only at real paint/clip discontinuities.

    Word extraction is spatial, whereas masks, other glyphs and clip changes
    happen in painting order. Keeping a whole word at its first character's
    order can erase later glyphs with an intervening source white mask.
    """
    runs=[]
    for char in word.get("chars",[]):
        fallback=char_order.get(_char_key(char),(fallback_order,[]))
        order=char.get("vwc_paint_order",fallback[0])
        clips=char.get("vwc_clips",fallback[1])
        if runs and order==runs[-1]["orders"][-1]+1 and clips==runs[-1]["clips"]:
            runs[-1]["chars"].append(char);runs[-1]["orders"].append(order)
        else:
            runs.append({"chars":[char],"orders":[order],"clips":clips})
    return runs


def _paint_run_geometry(page, chars, rotation, fallback_size):
    """Locate a run from its real characters, never an evenly divided word box."""
    box=[min(c["x0"] for c in chars),min(c["top"] for c in chars),
         max(c["x1"] for c in chars),max(c["bottom"] for c in chars)]
    size=sum(c.get("vwc_font_size",c.get("size",fallback_size)) for c in chars)/len(chars)
    if abs(rotation/90-round(rotation/90))<.0001:
        vertical=abs(round(rotation/90))%2
        return box,(box[0]+box[2])/2,(box[1]+box[3])/2,size,box[3]-box[1] if vertical else box[2]-box[0]
    theta=math.radians(rotation);u=(math.cos(theta),math.sin(theta));v=(-u[1],u[0])
    origins=[page.point2coord((c["matrix"][4],c["matrix"][5])) for c in chars]
    along=[p[0]*u[0]+p[1]*u[1] for p in origins]
    last=chars[-1];advance=abs(last.get("adv",0))*math.hypot(*last["matrix"][:2])
    if advance<=0:
        corners=[(last[x],last[y]) for x,y in (("x0","top"),("x1","top"),("x0","bottom"),("x1","bottom"))]
        projected=[x*u[0]+y*u[1] for x,y in corners];advance=max(projected)-min(projected)
    length=along[-1]-along[0]+advance
    across=sum(((c["x0"]+c["x1"])/2)*v[0]+((c["top"]+c["bottom"])/2)*v[1] for c in chars)/len(chars)
    center=(along[0]+along[-1]+advance)/2
    if length<=0:raise ValueError("A source text paint run has no safe reading-axis extent")
    return box,center*u[0]+across*v[0],center*u[1]+across*v[1],size,length


def _paint_run_texts(word, runs):
    values=[c.get("text","") for c in word["chars"]]
    if "".join(values)!=word["text"]:
        # pdfplumber expands standard Latin ligatures in word text; retain that
        # established logical spelling without guessing arbitrary glyphs.
        ligatures={"\ufb00":"ff","\ufb01":"fi","\ufb02":"fl","\ufb03":"ffi","\ufb04":"ffl","\ufb05":"st","\ufb06":"st"}
        values=["".join(ligatures.get(c,c) for c in value) for value in values]
        if "".join(values)!=word["text"]:
            raise ValueError("Logical source text cannot safely map to its character paint runs")
    result=[];offset=0
    for run in runs:
        end=offset+len(run["chars"]);result.append("".join(values[offset:end]));offset=end
    return result


def build_inventory(documents: list[dict], source_index: dict | Any) -> dict:
    """Extract only indexed plan/elevation crops from original project sources.

    The result uses ``views`` as a list. Each entry includes full native
    ``primitives`` plus a compact ``summary`` suitable for a model request.
    ID order follows native page object order and does not depend on the crop.
    """
    import pdfplumber
    index = source_index.model_dump() if hasattr(source_index,"model_dump") else source_index
    views = [_view_record(v) for v in index.get("views",[]) if _view_record(v).get("kind") in ("plan","elevation")]
    if len(views) > 100 or len({v["id"] for v in views}) != len(views):
        raise ValueError("Source drawing view identities are invalid")
    docs = {d["id"]:d for d in documents}
    result, unsupported = [], []
    for document_id in dict.fromkeys(v["document_id"] for v in views):
        document = docs.get(document_id)
        if document is None:
            raise ValueError("A drawing view cites an unknown project source")
        path = Path(document["local_path"])
        if path.suffix.lower() != ".pdf":
            unsupported.append(document_id)
            continue
        if not 0 < path.stat().st_size <= MAX_DOCUMENT_BYTES:
            raise ValueError("Source PDF size exceeds native extraction limit")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if document.get("sha256") and document["sha256"] != digest:
            raise ValueError("The imported source PDF changed after import")
        document_views = [v for v in views if v["document_id"]==document_id]
        with pdfplumber.open(path) as pdf:
            for number in dict.fromkeys(v["page"] for v in document_views):
                if not 1 <= number <= len(pdf.pages):
                    raise ValueError("A native view cites an unavailable PDF page")
                page = pdf.pages[number-1]
                native,char_order = _ordered_native(page,number)
                if len(native) > MAX_PAGE_PRIMITIVES:
                    raise ValueError("PDF page has too many native drawing primitives")
                # Bottom-to-top prevents reversing rotated dimension strings.
                words = _extract_words(page)
                for view in (v for v in document_views if v["page"]==number):
                    region = view.get("region")
                    if region is None or len(region)!=4 or not 0<=region[0]<region[2]<=1 or not 0<=region[1]<region[3]<=1:
                        raise ValueError("Native drafting requires a reviewed normalized source region")
                    crop=[region[0]*page.width,region[1]*page.height,region[2]*page.width,region[3]*page.height]
                    dx,dy=crop[:2]; width,height=crop[2]-dx,crop[3]-dy
                    primitives,styles=[],{}
                    text_paint_runs={}
                    for source_id,item,paint_order in native:
                        box=_bbox(item)
                        if not _intersects(box,crop):
                            continue
                        if abs(box[2]-box[0])+abs(box[3]-box[1])<.02:
                            continue  # zero-length native artifacts are not physical edges
                        style,definition=_style(item,"path"); styles[style]=definition
                        commands=_native_commands(item,dx,dy)
                        if len(commands)>5000:
                            raise ValueError("A source path exceeds the safe command limit")
                        filled = bool(item.get("fill"));stroked=bool(item.get("stroke",True))
                        if not filled and not stroked:continue
                        fill_color=_color(item.get("non_stroking_color"))
                        fill = "white" if filled and fill_color=="#ffffff" else "black" if filled else "none"
                        clips=[DrawingClip(commands=_native_commands(clip,dx,dy),fill_rule=clip["fill_rule"]) for clip in item.get("vwc_clips",[]) if clip["path"]]
                        # Gray fill-only backgrounds are surface shading, not contour strokes.
                        # Omit that shading in the clean drawing, retaining the source style and
                        # native primitive for explicit review/reclassification. White void masks
                        # and pure black arrows remain active and in the original paint order.
                        gray_shading=filled and not stroked and fill_color not in ("#000000","#ffffff") and len(set((fill_color[1:3],fill_color[3:5],fill_color[5:7])))==1
                        primitive=DrawingPrimitive(id=source_id,source_id=source_id,source_style_id=style,kind="path",
                            commands=commands,role="texture" if gray_shading else "opening" if definition["dash"] else "geometry",
                            stroke_width=max(.05,min(3,definition["width"])),stroke=stroked,
                            stroke_color="white" if definition["color"]=="#ffffff" else "ink",
                            dash=definition["dash"],fill=fill,
                            fill_rgb=fill_color if filled and fill_color not in ('#000000','#ffffff') and len(set((fill_color[1:3],fill_color[3:5],fill_color[5:7])))==1 else None,
                            fill_rule="evenodd" if item.get("evenodd") else "nonzero",clips=clips,
                            bbox=[box[0]-dx,box[1]-dy,box[2]-dx,box[3]-dy])
                        primitives.append((paint_order,primitive.model_dump()))
                    for i,word in enumerate(words):
                        box=_bbox(word)
                        if not _intersects(box,crop):
                            continue
                        chars=word.get("chars",[])
                        style,definition=_style(chars[0] if chars else {},"text");styles[style]=definition
                        upright=word.get("upright",True)
                        font_size=word.get("_font_size",box[3]-box[1] if upright else box[2]-box[0])
                        text_length=word.get("_text_length",box[2]-box[0] if upright else box[3]-box[1])
                        if not word.get("text") or font_size<=0 or text_length<=0:
                            continue
                        paint_order,word_clips=min((char_order.get(_char_key(char),(len(native)+i,[])) for char in chars),key=lambda pair:pair[0],default=(len(native)+i,[]))
                        clips=[DrawingClip(commands=_native_commands(clip,dx,dy),fill_rule=clip["fill_rule"]) for clip in word_clips if clip["path"]]
                        primitive=DrawingPrimitive(id=f"P{number}-T{i:06d}",source_id=f"P{number}-T{i:06d}",source_style_id=style,
                            kind="text",role=_default_text_role(word["text"]),text=word["text"],
                            x=word.get("_x",(box[0]+box[2])/2)-dx,y=word.get("_y",(box[1]+box[3])/2)-dy,font_size=min(font_size,200),
                            text_length=text_length,rotation=word.get("_angle",0 if upright else -90),clips=clips,
                            bbox=[box[0]-dx,box[1]-dy,box[2]-dx,box[3]-dy])
                        runs=_word_paint_runs(word,char_order,len(native)+i)
                        if len(runs)<=1:
                            # Preserve existing primitive bytes/IDs for ordinary
                            # contiguous words and all their old reviewed views.
                            primitives.append((paint_order,primitive.model_dump()))
                            continue
                        run_records=[]
                        for ordinal,(run,text) in enumerate(zip(runs,_paint_run_texts(word,runs)),1):
                            run_box,x,y,size,length=_paint_run_geometry(page,run["chars"],primitive.rotation,primitive.font_size)
                            run_clips=[DrawingClip(commands=_native_commands(clip,dx,dy),fill_rule=clip["fill_rule"])
                                       for clip in run["clips"] if clip["path"]]
                            run_style,run_definition=_style(run["chars"][0],"text");styles[run_style]=run_definition
                            child=primitive.model_copy(deep=True)
                            child.id=primitive.id+f"_RUN_{ordinal:03d}"
                            child.text=text;child.x=x-dx;child.y=y-dy
                            child.font_size=min(size,200);child.text_length=length;child.clips=run_clips
                            child.source_style_id=run_style
                            child.bbox=[run_box[0]-dx,run_box[1]-dy,run_box[2]-dx,run_box[3]-dy]
                            primitives.append((run["orders"][0],child.model_dump()))
                            run_records.append({"id":child.id,"text":text,"bbox":child.bbox,
                                                "paint_orders":run["orders"],"clip_count":len(child.clips)})
                        text_paint_runs[primitive.source_id]={"id":primitive.source_id,"text":word["text"],
                            "rotation":primitive.rotation,"bbox":primitive.bbox,"runs":run_records}
                    primitives=[p for _,p in sorted(primitives,key=lambda pair:pair[0])]
                    if len(primitives)>MAX_VIEW_PRIMITIVES:
                        raise ValueError("Source view is too dense; select a smaller source region")
                    style_counts=Counter(p["source_style_id"] for p in primitives)
                    examples=defaultdict(list)
                    for p in primitives:
                        if len(examples[p["source_style_id"]])<4:
                            examples[p["source_style_id"]].append({"id":p["id"],"source_kind":_source_kind(p["source_id"]),"bbox":[round(x,2) for x in p["bbox"]],"text":p["text"]})
                    logical_texts=[];seen_texts=set()
                    for primitive in primitives:
                        if primitive["kind"]!="text":continue
                        logical=text_paint_runs.get(primitive["source_id"])
                        if logical is not None:
                            if logical["id"] in seen_texts:continue
                            seen_texts.add(logical["id"])
                            entry={"id":logical["id"],"text":logical["text"],"rotation":round(logical["rotation"],4),
                                "bbox":[round(x/width if i%2==0 else x/height,4) for i,x in enumerate(logical["bbox"])],
                                "paint_runs":[{"id":run["id"],"text":run["text"],"paint_orders":run["paint_orders"],
                                    "clip_count":run["clip_count"],"bbox":[round(x/width if i%2==0 else x/height,4) for i,x in enumerate(run["bbox"])]}
                                    for run in logical["runs"]]}
                        else:
                            entry={"id":primitive["id"],"text":primitive["text"],"rotation":round(primitive["rotation"],4),
                                "bbox":[round(x/width if i%2==0 else x/height,4) for i,x in enumerate(primitive["bbox"])]}
                        logical_texts.append(entry)
                    record={"id":view["id"],"label":view["label"],"kind":view["kind"],"document_id":document_id,
                            "page":number,"region":region,"source_sha256":digest,"width":width,"height":height,
                            "primitives":primitives,"pending":[]}
                    record["summary"]={"primitive_count":len(primitives),"coordinate_units":"native displayed PDF points; NTS, not physical mm",
                        "style_simplification":"Black geometry, blue dimension text. Fill-only gray surface shading defaults to omitted texture; white visibility masks and black symbols are preserved. Native stroke texture requires explicit source-based classification.",
                        "styles":[dict(id=k,count=n,**styles[k],examples=examples[k]) for k,n in style_counts.most_common()],
                        "texts":logical_texts[:1000]}
                    result.append(record)
                page.close()
    order={v["id"]:i for i,v in enumerate(views)}
    result.sort(key=lambda v:order[v["id"]])
    return {"schema":"vwc-native-source-inventory/1","views":result,"unsupported_documents":unsupported,
            "warnings":["Image sources need explicit reconstructed 2D paths; native PDF extraction is unavailable."] if unsupported else []}


def _simple_paths(record):
    width,height=record["width"],record["height"]
    labels=[p for p in record["primitives"] if p["kind"]=="text" and p["role"]=="dimension"]
    paths=[]
    for primitive in record["primitives"]:
        commands=primitive["commands"]
        if primitive["kind"]!="path" or not 2<=len(commands)<=5 or any(c["op"] not in ("M","L","Z") for c in commands) or sum(c["op"]=="M" for c in commands)!=1:
            continue
        if primitive["role"]=="texture" or not ((primitive.get("stroke",True) and primitive.get("stroke_color","ink")=="ink") or primitive["fill"]=="black"):
            continue
        box=primitive["bbox"];points=[c["points"] for c in commands if c["points"]]
        if len(points)<2:continue
        axis="other"
        if len(commands)==2:
            if abs(points[0][0]-points[1][0])<.01:axis="v"
            elif abs(points[0][1]-points[1][1])<.01:axis="h"
        near=100000.
        for label in labels:
            b=label["bbox"];scale=max(label["font_size"],4.)
            dx=max(b[0]-box[2],box[0]-b[2],0.)/scale
            dy=max(b[1]-box[3],box[1]-b[3],0.)/scale
            near=min(near,math.hypot(dx,dy))
        margin=min(abs(box[0]/width),abs(box[1]/height),abs(1-box[2]/width),abs(1-box[3]/height))
        tier=0 if near<=3 else 1 if margin<=.17 else 2
        length=math.dist(points[0],points[-1])
        priority=(tier,0 if axis!="other" else 1,round(near,4) if tier==0 else round(margin,4),-round(length,3),primitive["id"])
        paths.append((priority,{"id":primitive["id"],"source_kind":_source_kind(primitive["source_id"]),"style_id":primitive["source_style_id"],"role":primitive["role"],
            "bbox":[round(value/(width if index%2==0 else height),4) for index,value in enumerate(box)],
            "points":[[round(point[0]/width,4),round(point[1]/height,4)] for point in points],
            "closed":commands[-1]["op"]=="Z","axis":axis,"dash":primitive["dash"]}))
    paths.sort(key=lambda item:item[0])
    return [item[1] for item in paths]


def _path_grid(record):
    cells=defaultdict(Counter);roles=defaultdict(Counter);totals=Counter()
    for primitive in record["primitives"]:
        if primitive["kind"]!="path":continue
        box=primitive["bbox"];w=record["width"];h=record["height"]
        left=max(0,min(7,math.floor(box[0]/w*8)));right=max(0,min(7,math.floor(box[2]/w*8)))
        top=max(0,min(7,math.floor(box[1]/h*8)));bottom=max(0,min(7,math.floor(box[3]/h*8)))
        for x in range(left,right+1):
            for y in range(top,bottom+1):
                cells[x,y][primitive["source_style_id"]]+=1;roles[x,y][primitive["role"]]+=1;totals[x,y]+=1
    return {"size":[8,8],"counting":"Native path bbox intersections; a path may occupy multiple cells.","cells":[
        {"cell":list(key),"count":totals[key],"roles":dict(roles[key]),"styles":[[style,count] for style,count in cells[key].most_common(3)]}
        for key in sorted(cells)]}


def compact_inventory(inventory: dict, *, path_limit: int = 2000, per_view_limit: int = 400) -> dict:
    """Bounded source-ID query hints, never a limit on retained native geometry."""
    if type(path_limit) is not int or type(per_view_limit) is not int or not 0<=path_limit<=6000 or not 0<=per_view_limit<=1200:
        raise ValueError("Invalid compact source path query budget")
    views=inventory["views"];paths=[_simple_paths(record) for record in views]
    allocations=[0]*len(views);remaining=path_limit
    while remaining:
        active=[i for i,items in enumerate(paths) if allocations[i]<min(per_view_limit,len(items))]
        if not active:break
        share=max(1,remaining//len(active))
        for index in active:
            take=min(share,remaining,per_view_limit-allocations[index],len(paths[index])-allocations[index])
            allocations[index]+=take;remaining-=take
            if not remaining:break
    output=[]
    for index,record in enumerate(views):
        item={key:value for key,value in record.items() if key!="primitives"}
        item["summary"]=dict(record["summary"])
        item["summary"]["straight_paths"]={"eligible_count":len(paths[index]),"provided_count":allocations[index],
            "truncated":allocations[index]<len(paths[index]),
            "coordinate_units":"Normalized source crop; NTS, not physical dimensions.",
            "selection":"Fair-share bounded IDs, prioritizing printed dimension bands and outer witness bands. Omitted query hints remain in native geometry.",
            "records":paths[index][:allocations[index]]}
        item["summary"]["path_grid"]=_path_grid(record)
        output.append(item)
    return {"schema":inventory["schema"],"warnings":inventory.get("warnings",[]),"views":output}
