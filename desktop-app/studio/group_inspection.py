"""Bounded diagnostic crops for held native groups, never semantic answers."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import math
from pathlib import Path

from PIL import Image,ImageDraw

from .drawing_models import DrawingView,DrawingPrimitive
from .drafting import render_pdf,drawing_hash,_review_note_layout
from .reference_layout import paper_layout

MAX_INSPECTION_GROUPS=12
MAX_INSPECTION_MEMBERS=96
MAX_INSPECTION_COMMANDS=4096
MAX_NATIVE_RECORD_BYTES=200000
MAX_PANEL_PIXELS=720
MAX_NATIVE_SCALE=24.


def _plain(value):return value.model_dump() if hasattr(value,'model_dump') else copy.deepcopy(value)
def _sha(value):return hashlib.sha256(value).hexdigest()
def _hash(value):return _sha(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode())


def _bounded_records(value):
    data=bytearray()
    for chunk in json.JSONEncoder(sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).iterencode(value):
        raw=chunk.encode('utf-8')
        if len(data)+len(raw)>MAX_NATIVE_RECORD_BYTES:return None
        data.extend(raw)
    return bytes(data)


def _write(path,data):
    if path.exists():
        if path.read_bytes()!=data:raise ValueError('Held-group inspection evidence changed at an existing immutable path')
    else:path.write_bytes(data)


def _pdf_roi(data,page_number,roi):
    """Render the real PDF ROI directly; never upscale a whole-view bitmap."""
    import pypdfium2 as pdfium
    from .documents import _PDF_RENDER_LOCK
    with _PDF_RENDER_LOCK,pdfium.PdfDocument(data) as document:
        if not 1<=page_number<=len(document):raise ValueError('Held-group inspection cites an unavailable PDF page')
        page=document[page_number-1]
        try:
            width,height=page.get_size();left,top,right,bottom=roi
            if not (0<=left<right<=width and 0<=top<bottom<=height):
                raise ValueError('Held-group inspection ROI lies outside the displayed PDF page')
            scale=min(MAX_NATIVE_SCALE,(MAX_PANEL_PIXELS-1)/max(right-left,bottom-top))
            bitmap=page.render(scale=scale,crop=(left,height-bottom,width-right,top))
            try:image=bitmap.to_pil().convert('RGB').copy()
            finally:bitmap.close()
        finally:page.close()
    if max(image.size)>MAX_PANEL_PIXELS:
        raise ValueError('Held-group native inspection exceeded its pixel bound')
    return image,{'pdf_roi_points':list(roi),'native_render_scale':scale,
        'requested_native_scale':MAX_NATIVE_SCALE,'pixel_size':list(image.size),
        'resolution_limited_by':'panel_pixel_cap' if scale<MAX_NATIVE_SCALE else None,
        'direct_pdf_roi_render':True,'whole_view_bitmap_upscaled':False}


def build_held_group_inspections(*,groups,inventory,drawings,documents,rendered,output_dir,prefix,check_control=None):
    """Build only the caller's requested held groups; all evidence stays bound.

    An unavailable/overbound detail is disclosed, never silently subsetted or
    treated as a resolved group. Full source/current views remain necessary.
    """
    inventory=inventory.model_dump() if hasattr(inventory,'model_dump') else inventory
    sources={view['id']:view for view in inventory['views']}
    views={view.id if isinstance(view,DrawingView) else view['id']:
        view if isinstance(view,DrawingView) else DrawingView.model_validate(view) for view in drawings}
    docs={item['id']:item for item in documents};output=Path(output_dir);output.mkdir(parents=True,exist_ok=True)
    limits={'max_groups':MAX_INSPECTION_GROUPS,'max_members_per_group':MAX_INSPECTION_MEMBERS,
        'max_commands_per_group':MAX_INSPECTION_COMMANDS,'max_panel_pixels':MAX_PANEL_PIXELS,
        'max_native_record_bytes':MAX_NATIVE_RECORD_BYTES,
        'requested_native_scale':MAX_NATIVE_SCALE,'panels_per_image':4}
    manifest=[];images=[];unavailable=[];identities=set()
    for number,raw_group in enumerate(sorted(groups,key=lambda item:(item['view_id'],item['group_id']))):
        if check_control:check_control()
        group=_plain(raw_group);key=(group['view_id'],group['group_id'])
        if key in identities:raise ValueError('Held-group inspection identities must be unique')
        identities.add(key)
        if key[0] not in sources or key[0] not in views:raise ValueError('Held-group inspection cites a foreign source view')
        source=sources[key[0]];view=views[key[0]]
        for field in ('document_id','page','source_sha256','region','width','height'):
            if source[field]!=getattr(view,field):raise ValueError('Held-group source and saved candidate view identity differ')
        ids=group.get('native_ids',[])
        if not ids or len(ids)!=len(set(ids)):raise ValueError('Held-group inspection requires exact unique native members')
        members_sha=_hash(sorted(ids))
        if group.get('native_members_sha256',members_sha)!=members_sha:
            raise ValueError('Held-group inspection native membership hash changed')
        lookup={item['id']:item for item in source['primitives']}
        if set(ids)-set(lookup):raise ValueError('Held-group inspection contains foreign native members')
        if group.get('page',source['page'])!=source['page'] or group.get('region',source['region'])!=source['region']:
            raise ValueError('Held-group inspection source page or frame changed')
        record={'group_id':key[1],'view_id':key[0],'native_members_sha256':members_sha,'native_ids':sorted(ids),
            'source_sha256':source['source_sha256'],'candidate_view_sha256':drawing_hash(view),
            'document_id':source['document_id'],'page':source['page'],'source_view_region':source['region'],
            'diagnostic_only':True,'semantic_disposition_supplied':False}
        members=[lookup[ident] for ident in sorted(ids)]
        command_count=sum(len(item.get('commands',[]))+sum(len(clip.get('commands',[])) for clip in item.get('clips',[])) for item in members)
        reason=('group_count_limit' if number>=MAX_INSPECTION_GROUPS else
            'member_count_limit' if len(members)>MAX_INSPECTION_MEMBERS else
            'command_count_limit' if command_count>MAX_INSPECTION_COMMANDS else None)
        member_bytes=None if reason else _bounded_records(members)
        if not reason and member_bytes is None:reason='native_record_byte_limit'
        if reason:
            record.update(available=False,unavailable_reason=reason);manifest.append(record);unavailable.append(key[1]);continue
        box=[min(item['bbox'][0] for item in members),min(item['bbox'][1] for item in members),
             max(item['bbox'][2] for item in members),max(item['bbox'][3] for item in members)]
        if group.get('bbox',box)!=box:raise ValueError('Held-group inspection bounds do not match its exact native members')
        pad=max(4.,max((float(item.get('stroke_width',.5))*4 for item in members if item.get('stroke')),default=0.),
            max(box[2]-box[0],box[3]-box[1])*.08)
        roi=[max(0.,box[0]-pad),max(0.,box[1]-pad),min(view.width,box[2]+pad),min(view.height,box[3]+pad)]
        if roi[2]<=roi[0] or roi[3]<=roi[1]:
            record.update(available=False,unavailable_reason='outside_visible_source_frame');manifest.append(record);unavailable.append(key[1]);continue
        document=docs.get(source['document_id'])
        if document is None or document['sha256']!=source['source_sha256']:
            raise ValueError('Held-group inspection original document SHA binding changed')
        original_bytes=Path(document['local_path']).read_bytes()
        if _sha(original_bytes)!=source['source_sha256']:raise ValueError('Held-group inspection original PDF bytes changed')
        candidates=[item for item in rendered if item['view_id']==view.id and str(item['path']).lower().endswith('.pdf')]
        if len(candidates)!=1:raise ValueError('Held-group inspection requires one current saved candidate PDF per view')
        current_record=candidates[0];current_bytes=Path(current_record['path']).read_bytes()
        if _sha(current_bytes)!=current_record['sha256']:raise ValueError('Held-group inspection saved PDF artifact changed')
        # Original displayed-page coordinates include the pinned view offset.
        import pypdfium2 as pdfium
        from .documents import _PDF_RENDER_LOCK
        with _PDF_RENDER_LOCK,pdfium.PdfDocument(original_bytes) as pdf:
            page=pdf[source['page']-1]
            try:page_width,page_height=page.get_size()
            finally:page.close()
        left,top,right,bottom=source['region']
        if not (math.isclose((right-left)*page_width,view.width,abs_tol=1e-4)
                and math.isclose((bottom-top)*page_height,view.height,abs_tol=1e-4)):
            raise ValueError('Held-group source/native displayed-coordinate basis differs')
        source_roi=[left*page_width+roi[0],top*page_height+roi[1],left*page_width+roi[2],top*page_height+roi[3]]
        source_image,source_proof=_pdf_roi(original_bytes,source['page'],source_roi)
        layout=paper_layout(view,_review_note_layout(view)[1]);ox,oy=layout['origin']
        current_image,current_proof=_pdf_roi(current_bytes,1,[ox+roi[0],oy+roi[1],ox+roi[2],oy+roi[3]])
        # Exact members are reconstructed only as an explicitly diagnostic ink
        # isolation. The unmodified original PDF panel remains authoritative.
        native=[DrawingPrimitive.model_validate(item) for item in members]
        for item in native:item.role='geometry'
        isolated=DrawingView(id=view.id,label='Native member isolation',kind=view.kind,document_id=view.document_id,
            page=view.page,region=view.region,source_sha256=view.source_sha256,width=view.width,height=view.height,primitives=native)
        isolated_bytes=render_pdf(isolated);origin=paper_layout(isolated)['origin']
        isolated_image,isolated_proof=_pdf_roi(isolated_bytes,1,[origin[0]+roi[0],origin[1]+roi[1],origin[0]+roi[2],origin[1]+roi[3]])
        # PDFium rounds the absolute page/crop edges independently. The same
        # native span at different paper offsets can therefore differ by one
        # pixel. Preserve each direct render instead of resizing or implying
        # exact pixel registration between different PDF pages.
        context_image=source_image.copy();context_draw=ImageDraw.Draw(context_image)
        sx=source_image.width/(roi[2]-roi[0]);sy=source_image.height/(roi[3]-roi[1])
        context_draw.rectangle([(max(0.,box[0]-roi[0])*sx,max(0.,box[1]-roi[1])*sy),
            ((min(roi[2],box[2])-roi[0])*sx,(min(roi[3],box[3])-roi[1])*sy)],outline='#c02020',width=1)
        card=Image.new('RGB',(MAX_PANEL_PIXELS*2+24,MAX_PANEL_PIXELS*2+80),'#edf0ed');draw=ImageDraw.Draw(card)
        draw.text((8,6),key[1]+' / '+key[0]+' - diagnostics, no semantic answer',fill='black')
        for slot,(label,panel) in enumerate([('ORIGINAL PDF / native ROI',source_image),('CURRENT SAVED PDF / same ROI',current_image),
                ('EXACT SOURCE MEMBERS / diagnostic isolation',isolated_image),('NATIVE GROUP BOUNDS / diagnostic context',context_image)]):
            x=8+(slot%2)*(MAX_PANEL_PIXELS+8);y=28+(slot//2)*(MAX_PANEL_PIXELS+24)
            draw.text((x,y),label,fill='black');card.paste(panel,(x,y+18))
        stem=prefix+'-'+_hash([key[0],key[1]])[:20];image_path=output/(stem+'.png')
        stream=io.BytesIO();card.save(stream,format='PNG');image_bytes=stream.getvalue();_write(image_path,image_bytes)
        record.update(available=True,native_roi_points=roi,native_records=copy.deepcopy(members),
            native_records_sha256=_sha(member_bytes),current_pdf_artifact_id=current_record['artifact_id'],
            current_pdf_sha256=current_record['sha256'],source_pdf_sha256=_sha(original_bytes),
            panels={'source':source_proof,'current':current_proof,'isolated':isolated_proof},
            panel_alignment='Same native ROI; independent direct PDF pixel grids, no resize or pixel-mask registration.',
            context_overlay={'kind':'exact_native_group_bbox','native_bbox':box,'diagnostic_only':True},
            image_artifact_id=image_path.name,image_sha256=_sha(image_bytes),image_pixels=list(card.size))
        manifest.append(record);images.append(image_path)
    result={'schema':'vwc-held-group-inspection/1','manifest':manifest,'limits':limits,
        'complete':not unavailable,'unavailable_group_ids':unavailable,
        'authority':'Mechanical source/current/native-member diagnostics only; no retain/omit/required/harmless answer or automatic group resolution.'}
    manifest_path=output/(prefix+'-manifest.json');_write(manifest_path,json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False).encode())
    return {**result,'images':images,'manifest_path':manifest_path}
