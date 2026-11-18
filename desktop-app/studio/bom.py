"""Deterministic explicit-board list and Excel export, independent of AI/meshes."""
from __future__ import annotations

import hashlib
import io
import json
import math
import re

from .material_models import board_kind


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def _fit_stock(length,width,spec,variant):
    if not variant.stock_sizes:return True
    if spec.grain=="none" or variant.grain=="none":orientations=[(length,width),(width,length)]
    elif spec.grain==variant.grain:orientations=[(length,width)]
    else:orientations=[(width,length)]
    return any(a<=stock.length_mm+1e-6 and b<=stock.width_mm+1e-6
               for a,b in orientations for stock in variant.stock_sizes)


def _positive_dimensions(values):
    return all(value is not None and math.isfinite(value) and value > 0 for value in values)


def _suggested_board(part, resolver):
    if part.profile is not None or part.mesh is not None:
        return None
    sizes = [resolver.expression(value)[0] for value in part.size]
    if not _positive_dimensions(sizes):
        return None
    ordered = sorted(zip("XYZ", sizes), key=lambda axis_size: axis_size[1])
    (thickness_axis, thickness), (width_axis, width), (length_axis, length) = ordered
    if thickness > width / 2:
        return None
    return {"length_axis": length_axis, "width_axis": width_axis, "thickness_axis": thickness_axis,
            "length_mm": length, "width_mm": width, "thickness_mm": thickness}


def _review_board_row(part, path, dimensions, snapshot, spec, codes, reasons):
    variant = snapshot.variant if snapshot is not None else None
    length, width = dimensions["length_mm"], dimensions["width_mm"]
    area = length * width / 1e6
    source_code = part.material.strip()
    if source_code.casefold() in ("none", "unspecified"):
        source_code = ""
    return {"row_id": _digest({"review_part": part.id}), "part_ids": [part.id], "part_names": [part.name],
            "contexts": [{"part_id": part.id, "context_path": path}], **dimensions,
            "cut_length_mm": length + spec.allowance_length_mm if spec is not None else None,
            "cut_width_mm": width + spec.allowance_width_mm if spec is not None else None,
            "quantity": 1, "piece_area_m2": area, "area_m2": area,
            "material_snapshot_id": snapshot.snapshot_id if snapshot is not None else None,
            "material_variant_id": variant.id if variant is not None else None,
            "material_version": variant.version if variant is not None else None,
            "material_code": variant.code if variant is not None else source_code,
            "material_name": variant.name if variant is not None else "",
            "color_name": variant.color_name if variant is not None else "",
            "color_hex": variant.color_hex if variant is not None else "",
            "substrate": variant.substrate if variant is not None else "",
            "finish": variant.finish if variant is not None else "",
            "grain": spec.grain if spec is not None else None,
            "edges": list(spec.edges) if spec is not None else [], "profile": "rectangle",
            "machining_notes": spec.machining_notes if spec is not None else "",
            "spec_status": "saved" if spec is not None else "suggested",
            "review_reason_codes": codes, "review_reasons": reasons,
            **({"material_category": variant.category} if variant is not None else {})}


def build_bom(model,project_id,revision,*,scope_id=None):
    from .geometry import validate_model,Resolver,find_part
    if not isinstance(project_id,str) or not project_id or type(revision) is not int or revision<1:
        raise ValueError("A board list requires a project identity and positive revision")
    model=validate_model(model);resolver=Resolver(model)
    scope=find_part(model,scope_id) if scope_id is not None else None
    if scope is not None and (scope.id==model.root.id or not scope.children):
        raise ValueError("Choose a saved cabinet or assembly for the cutting list")
    snapshots={snapshot.snapshot_id:snapshot for snapshot in model.material_snapshots}
    rows={};review_rows=[];blocked=[];excluded=[];used=set()
    def walk(part,ancestors,inherited_context=False,in_scope=False):
        context=inherited_context or part.context
        in_scope=in_scope or scope is None or part.id==scope.id
        if not in_scope:
            for child in part.children:walk(child,[*ancestors,part],context)
            return
        path=[{"id":p.id,"name":p.name,"kind":p.kind} for p in ancestors]
        info={"part_id":part.id,"part_name":part.name,"context_path":path}
        def issue(target,codes,reasons,**details):
            target.append({**info,"reason_codes":codes,"reasons":reasons,"reason":"; ".join(reasons),**details})
        if context:issue(excluded,["context"],["Room/context geometry is not a cut board"])
        elif part.surface is not None:issue(excluded,["source_surface"],["An observed source face has no physical construction thickness"])
        elif not part.physical:issue(excluded,["nonphysical"],["An assembly/envelope or annotation is not a physical board"])
        elif part.children:issue(excluded,["physical_assembly"],["Use explicit physical leaf boards, not an assembly envelope"])
        elif part.board_spec is None:
            if board_kind(part.kind):
                suggested = _suggested_board(part, resolver)
                codes = ["missing_board_spec"]
                reasons = ["Declare length/width/thickness axes for this physical board"]
                issue(blocked, codes, reasons, **({"suggested_board": suggested} if suggested else {}))
                if suggested:
                    snapshot = snapshots.get(part.material_assignment)
                    if snapshot is not None:
                        used.add(snapshot.snapshot_id)
                    review_rows.append(_review_board_row(part, path, suggested, snapshot, None, codes, reasons))
            else:issue(excluded,["not_board"],["This physical solid has no explicit board specification"])
        else:
            spec=part.board_spec;codes=[];reasons=[]
            def block(code,message):codes.append(code);reasons.append(message)
            if part.profile is not None:block("nonrectangular_profile","This list supports rectangular board pieces only")
            sizes=[resolver.expression(value)[0] for value in part.size]
            axes=[{"X":0,"Y":1,"Z":2}[axis] for axis in (spec.length_axis,spec.width_axis,spec.thickness_axis)]
            length,width,thickness=[sizes[axis] for axis in axes]
            if any(value is None for value in (length,width,thickness)):
                block("unknown_dimensions","A local finished length, width or thickness is TBC")
            snapshot=snapshots.get(part.material_assignment)
            if snapshot is None:block("missing_material","Choose a pinned material variant for this board")
            else:
                used.add(snapshot.snapshot_id);variant=snapshot.variant
                if variant.category=="finish":block("finish_not_stock","A finish-only product is not a physical board substrate")
                elif variant.thickness_mm is None:block("unknown_material_thickness","The assigned stock thickness is unspecified")
                elif thickness is not None and not math.isclose(thickness,variant.thickness_mm,rel_tol=0,abs_tol=1e-6):
                    block("thickness_mismatch","Board thickness differs from the pinned material variant")
            if length is not None and width is not None:
                cut_length=length+spec.allowance_length_mm;cut_width=width+spec.allowance_width_mm
                if snapshot is not None and not _fit_stock(cut_length,cut_width,spec,snapshot.variant):
                    block("stock_fit","No known stock sheet fits the cutting dimensions with the selected grain direction")
            if codes:
                issue(blocked, codes, reasons)
                if part.profile is None and _positive_dimensions((length, width, thickness)):
                    dimensions = {"length_axis": spec.length_axis, "width_axis": spec.width_axis,
                                  "thickness_axis": spec.thickness_axis, "length_mm": length,
                                  "width_mm": width, "thickness_mm": thickness}
                    review_rows.append(_review_board_row(part, path, dimensions, snapshot, spec, codes, reasons))
            else:
                variant=snapshot.variant
                signature={"material_snapshot_id":snapshot.snapshot_id,"axes":[spec.length_axis,spec.width_axis,spec.thickness_axis],
                    "finished_size_mm":[length,width,thickness],"cut_size_mm":[cut_length,cut_width,thickness],
                    "grain":spec.grain,"edges":spec.edges,"profile":spec.profile,"machining_notes":spec.machining_notes}
                row_id=_digest(signature)
                if row_id not in rows:
                    rows[row_id]={"row_id":row_id,"part_ids":[],"part_names":[],"contexts":[],
                        "length_mm":length,"width_mm":width,"thickness_mm":thickness,
                        "cut_length_mm":cut_length,"cut_width_mm":cut_width,"quantity":0,
                        "piece_area_m2":length*width/1e6,"area_m2":0.,
                        "material_snapshot_id":snapshot.snapshot_id,"material_variant_id":variant.id,"material_version":variant.version,
                        "material_code":variant.code,"material_name":variant.name,"color_name":variant.color_name,
                        "color_hex":variant.color_hex,"substrate":variant.substrate,"finish":variant.finish,
                        "length_axis":spec.length_axis,"width_axis":spec.width_axis,"thickness_axis":spec.thickness_axis,
                        "grain":spec.grain,"edges":list(spec.edges),"profile":spec.profile,"machining_notes":spec.machining_notes}
                row=rows[row_id];row["part_ids"].append(part.id);row["part_names"].append(part.name)
                row["contexts"].append({"part_id":part.id,"context_path":path})
                row["quantity"]+=1;row["area_m2"]=row["piece_area_m2"]*row["quantity"]
        for child in part.children:walk(child,[*ancestors,part],context,in_scope)
    walk(model.root,[])
    ordered=[]
    for row in sorted(rows.values(),key=lambda r:r["row_id"]):
        by_id=sorted(zip(row["part_ids"],row["part_names"],row["contexts"]),key=lambda item:item[0])
        row["part_ids"],row["part_names"],row["contexts"]=[list(values) for values in zip(*by_id)]
        ordered.append(row)
    report={"project_id":project_id,"revision":revision,"units":"mm",
        "status":"blocked" if blocked else "ready" if ordered else "empty","rows":ordered,
        "review_rows": sorted(review_rows, key=lambda row: row["part_ids"][0]),
        "blocked":sorted(blocked,key=lambda r:r["part_id"]),"excluded":sorted(excluded,key=lambda r:r["part_id"]),
        "materials":[snapshots[key].model_dump(mode="json") for key in sorted(used)]}
    if scope is not None:
        report.update(scope_id=scope.id,scope_name=scope.name)
    report["bom_sha256"]=_digest(report)
    return report


def _xlsx_part_name(part_id,name,kind=None):
    """Present exact generated defaults in English without changing source names."""
    match=re.fullmatch(r".+/INTERIOR(?:/([^/]+))?",part_id)
    if match is None:return name
    suffix=match.group(1)
    if suffix is None:
        return "Designed interior" if kind in (None,"interior") and name=="Designed interior / 设计的内部结构" else name
    defaults={"LEFT":("Left carcass panel","左侧板"),"RIGHT":("Right carcass panel","右侧板"),
        "BOTTOM":("Bottom panel","底板"),"TOP":("Top panel","顶板"),"BACK":("Back panel","背板")}
    labels=defaults.get(suffix)
    if labels is None:
        if numbered:=re.fullmatch(r"DIVIDER-([1-9]\d*)",suffix):
            number=numbered.group(1);labels=(f"Divider {number}",f"竖隔板 {number}")
        elif numbered:=re.fullmatch(r"SHELF-([1-9]\d*)-([1-9]\d*)",suffix):
            number=".".join(numbered.groups());labels=(f"Shelf {number}",f"层板 {number}")
        elif drawer:=re.fullmatch(r"DRAWER-([1-9]\d*)-(BASE|LEFT|RIGHT|FRONT|BACK)",suffix):
            number,side=drawer.groups()
            english,chinese={"BASE":("bottom","底板"),"LEFT":("left","左侧"),"RIGHT":("right","右侧"),
                "FRONT":("front","前板"),"BACK":("back","后板")}[side]
            labels=(f"Drawer {number} {english}",f"抽屉 {number} {chinese}")
    return labels[0] if labels is not None and name==" / ".join(labels) else name


def _xlsx_context(path):
    return " / ".join(_xlsx_part_name(part["id"],part["name"],part["kind"]) for part in path)


def _xlsx_material_labels(code,name,color):
    """Only the known seeded sample defaults receive display translations."""
    if match:=re.fullmatch(r"SAMPLE-PLY-(18|16|6)",code):
        thickness=match.group(1)
        if name==f"Sample plywood {thickness} mm / 示例夹板 {thickness} 毫米":name=f"Sample plywood {thickness} mm"
        if color=="Sample natural / 示例原木色":color="Sample natural"
    return name,color


def export_bom_xlsx(report):
    """Export only a complete, bound board report; no toolpaths or nesting."""
    if report.get("status")!="ready" or not report.get("rows") or report.get("blocked"):
        raise ValueError("Resolve the blocked board specifications before exporting the cutting list")
    return _render_bom_xlsx(report)


def export_review_bom_xlsx(report):
    """Export modeled panel information with the unresolved items visible."""
    if not report.get("review_rows"):
        raise ValueError("There are no modeled panels to export for review")
    return _render_bom_xlsx(report, review=True)


def _render_bom_xlsx(report, *, review=False):
    if _digest({key:value for key,value in report.items() if key!="bom_sha256"})!=report.get("bom_sha256"):
        raise ValueError("The board report changed; regenerate it before export")
    from openpyxl import Workbook
    from openpyxl.styles import Font,PatternFill,Alignment
    from openpyxl.utils import get_column_letter
    book=Workbook();book.remove(book.active)
    metadata=["Project ID",report["project_id"],"Revision",report["revision"],"Units","mm","BOM SHA-256",report["bom_sha256"]]
    note=("Panel review. Flagged rows show modeled dimensions. Confirm panel specifications and stock before cutting."
          if review else "Board cutting list — no nesting, machining program or machine-specific NC output")
    if report.get("scope_id"):
        note=f'Cutting group {report["scope_name"]} ({report["scope_id"]}). {note}'
    illegal=re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
    def sheet(name,headers,data):
        ws=book.create_sheet(name)
        for row in [metadata,[note],headers,*data]:
            # openpyxl validates XML text while binding a cell during append,
            # before any post-append formula protection can run.
            ws.append([illegal.sub(lambda m:f"\\u{ord(m.group()):04x}",value) if isinstance(value,str) else value for value in row])
            for cell in ws[ws.max_row]:
                if isinstance(cell.value,str):
                    cell.data_type="s"
        ws.freeze_panes="C4";ws.auto_filter.ref=f"A3:{get_column_letter(len(headers))}{max(3,ws.max_row)}"
        widths={"Row ID":46,"Snapshot SHA-256":46,"Material snapshot SHA-256":46,
            "Board IDs":36,"Board ID":36,"Part ID":36,"Material ID":36,
            "Board names":32,"Board name":32,"Part name":32,"Material name":30,"Name":30,
            "Material code":22,"Code":22,"Color":20,"Color hex":13,"Context":44,
            "Reason":60,"Review notes":60,"Machining notes":42,"Substrate":28,"Finish":28,"Supplier":28,"SKU":22,
            "Stock sizes mm":32,"Quantity":11,"Version":10,"Grain":12,"Profile":14}
        for column,header in enumerate(headers,1):
            width=widths.get(header,18 if "Area" in header else 16 if "mm" in header else max(13,min(24,len(header)+2)))
            ws.column_dimensions[get_column_letter(column)].width=width
        # Only the metadata rows are merged; row 3 remains a plain machine-readable header.
        ws.merge_cells("H1:L1");ws.merge_cells("A2:L2")
        ws.row_dimensions[1].height=34;ws.row_dimensions[2].height=30;ws.row_dimensions[3].height=34
        for cell in ws[1]:
            cell.font=Font(name="Calibri",size=9,bold=True,color="173E38")
            cell.alignment=Alignment(vertical="center",wrap_text=True)
        ws["A2"].font=Font(name="Calibri",size=9,italic=True,color="586B61")
        ws["A2"].alignment=Alignment(vertical="center",wrap_text=True)
        for cell in ws[3][:len(headers)]:
            cell.font=Font(name="Calibri",size=10,bold=True,color="FFFFFF")
            cell.fill=PatternFill("solid",fgColor="173E38")
            cell.alignment=Alignment(vertical="center",wrap_text=True)
        for row in ws.iter_rows(min_row=4,max_col=len(headers)):
            line_count=1
            for cell,header in zip(row,headers):
                cell.font=Font(name="Calibri",size=10)
                cell.alignment=Alignment(vertical="top",wrap_text=True)
                if isinstance(cell.value,(float,int)):
                    cell.number_format="0" if header in ("Quantity","Version") else "0.0000" if "Area" in header else "0.0##" if "mm" in header else "General"
                elif cell.value is not None:
                    width=max(8,ws.column_dimensions[cell.column_letter].width-2)
                    lines=sum(max(1,math.ceil(sum(2 if ord(char)>255 else 1 for char in line)/width)) for line in str(cell.value).split("\n"))
                    line_count=max(line_count,lines)
                if header=="Color hex" and isinstance(cell.value,str) and re.fullmatch(r"#[0-9a-fA-F]{6}",cell.value):
                    color=cell.value[1:];channels=[int(color[i:i+2],16) for i in (0,2,4)]
                    cell.fill=PatternFill("solid",fgColor=color)
                    cell.font=Font(name="Calibri",size=10,color="FFFFFF" if sum(a*b for a,b in zip(channels,(.299,.587,.114)))<140 else "173E38")
            ws.row_dimensions[row[0].row].height=min(408,max(22,line_count*14+6))
        ws.sheet_view.zoomScale=80;ws.print_title_rows="1:3"
        ws.page_setup.orientation="landscape";ws.page_setup.paperSize=ws.PAPERSIZE_A3
        ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=0
        ws.sheet_properties.pageSetUpPr.fitToPage=True
        ws.print_options.horizontalCentered=False
        return ws
    if review:
        data=[]
        for row in [*report["rows"], *report["review_rows"]]:
            reasons=row.get("review_reasons", [])
            names=[_xlsx_part_name(part_id,name) for part_id,name in zip(row["part_ids"],row["part_names"])]
            context="; ".join(_xlsx_context(entry["context_path"]) for entry in row["contexts"])
            data.append(["Review needed" if reasons else "Ready", "; ".join(names), row["material_code"], row["material_name"],
                         row["length_mm"], row["width_mm"], row["thickness_mm"], row["quantity"], row["area_m2"],
                         row["grain"], " / ".join(row["edges"]), "; ".join(reasons), context, "; ".join(row["part_ids"])])
        sheet("Panel review", ["Status", "Board names", "Material code", "Material name", "Modeled length mm",
              "Modeled width mm", "Modeled thickness mm", "Quantity", "Area m2 total", "Grain", "Edges",
              "Review notes", "Context", "Board IDs"], data)
        output=io.BytesIO();book.save(output);return output.getvalue()

    headers=["Row ID","Board IDs","Board names","Material code","Material name","Color","Color hex",
        "Finished length mm","Finished width mm","Thickness mm","Cut length mm","Cut width mm","Quantity","Area m2 total",
        "Grain","Edge left","Edge right","Edge top","Edge bottom","Profile","Machining notes","Context","Material snapshot SHA-256"]
    cut=[];parts=[]
    for row in report["rows"]:
        context="; ".join(_xlsx_context(entry["context_path"]) for entry in row["contexts"])
        names=[_xlsx_part_name(part_id,name) for part_id,name in zip(row["part_ids"],row["part_names"])]
        material_name,color_name=_xlsx_material_labels(row["material_code"],row["material_name"],row["color_name"])
        cut.append([row["row_id"],"; ".join(row["part_ids"]),"; ".join(names),row["material_code"],material_name,color_name,row["color_hex"],
            row["length_mm"],row["width_mm"],row["thickness_mm"],row["cut_length_mm"],row["cut_width_mm"],row["quantity"],row["area_m2"],
            row["grain"],*row["edges"],row["profile"],row["machining_notes"],context,row["material_snapshot_id"]])
        for part_id,name,entry in zip(row["part_ids"],names,row["contexts"]):
            parts.append([part_id,name,row["row_id"],row["material_code"],color_name,row["length_mm"],row["width_mm"],row["thickness_mm"],
                row["cut_length_mm"],row["cut_width_mm"],1,row["piece_area_m2"],row["grain"],*row["edges"],
                _xlsx_context(entry["context_path"]),row["material_snapshot_id"]])
    sheet("Cut list",headers,cut)
    sheet("Parts",["Board ID","Board name","Row ID","Material code","Color","Length mm","Width mm","Thickness mm","Cut length mm","Cut width mm",
        "Quantity","Area m2","Grain","Edge left","Edge right","Edge top","Edge bottom","Context","Material snapshot SHA-256"],parts)
    sheet("Issues",["State","Part ID","Part name","Reason"],[[state,entry["part_id"],_xlsx_part_name(entry["part_id"],entry["part_name"]),entry["reason"]]
        for state in ("blocked","excluded") for entry in report[state]])
    sheet("Materials",["Snapshot SHA-256","Material ID","Version","Code","Name","Color","Color hex","Category","Substrate","Finish","Thickness mm","Grain","Stock sizes mm","Supplier","SKU"],
        [[entry["snapshot_id"],entry["variant"]["id"],entry["variant"]["version"],entry["variant"]["code"],*_xlsx_material_labels(entry["variant"]["code"],entry["variant"]["name"],entry["variant"]["color_name"]),entry["variant"]["color_hex"],
          entry["variant"]["category"],entry["variant"]["substrate"],entry["variant"]["finish"],entry["variant"]["thickness_mm"],entry["variant"]["grain"],
          "; ".join(f"{size['length_mm']} x {size['width_mm']}" for size in entry["variant"]["stock_sizes"]),entry["variant"]["supplier"],entry["variant"]["sku"]] for entry in report["materials"]])
    output=io.BytesIO();book.save(output);return output.getvalue()
