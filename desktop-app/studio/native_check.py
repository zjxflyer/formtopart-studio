"""Offline packaged-runtime check, explicitly invoked through a hidden CLI flag.

Only a generated synthetic fixture is used. This check makes no API requests,
opens no desktop windows, and reads no credentials or customer projects.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import zipfile


def run_native_check(output: Path) -> int:
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    artifacts={name:output.with_name(output.stem+'-'+name+suffix) for name,suffix in
               [('source','.pdf'),('drawing','.pdf'),('preview','.png'),('vectors','.svg'),('fixture','.vwc')]}
    checks=[]
    def check(name,passed):
        checks.append({'name':name,'passed':bool(passed)})
        if not passed:raise AssertionError(name)
    try:
        from pdfminer.cmapdb import CMapDB
        import reportlab
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from PIL import Image
        from pypdf import PdfReader
        import pypdfium2 as pdfium
        import pypdfium2.raw as raw
        from .models import StudioModel,Part,Parameter,SourceSurface,SourceView
        from .source_vectors import build_inventory
        from .drafting import compile_drawings,render_pdf,render_png,render_svg,stamp_review,drawing_hash
        from .drawing_state import semantic_fingerprint
        from .geometry import build_scene
        from .automatic_native_groups import build_automatic_catalog
        from .autonomous_2d import AutonomousGroupSelection, SourceScopeReview, RULES, MAX_REQUESTS
        from .ai import strict_schema
        from .reference_models import ReferencePlan
        from .api_drawing_workflow import ReviewReport

        check('packaged-cmap-data',bool(CMapDB.get_cmap('90ms-RKSJ-H').code2cid))
        font=Path(reportlab.__file__).parent/'fonts'/'Vera.ttf'
        check('packaged-reportlab-font-data',font.is_file())
        pdfmetrics.registerFont(TTFont('VWCReleaseFixture',str(font)))
        pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
        source=io.BytesIO();c=canvas.Canvas(source,pagesize=(300,200),invariant=1)
        c.setFont('VWCReleaseFixture',10);c.drawString(30,175,'600 mm')
        c.rect(20,30,120,100,fill=0,stroke=1)
        c.saveState();clip=c.beginPath();clip.moveTo(170,80);clip.lineTo(200,110);clip.lineTo(230,80);clip.lineTo(200,50);clip.close()
        c.clipPath(clip,stroke=0,fill=0);c.rect(170,50,60,60,fill=1,stroke=0);c.restoreState()
        c.saveState();c.translate(175,145);c.rotate(45);c.drawString(0,0,'3 1/2"');c.restoreState()
        c.setFont('STSong-Light',12);c.drawString(175,25,'木柜')
        c.showPage();c.save();source=source.getvalue();artifacts['source'].write_bytes(source)
        document_id='DOC_'+'1'*32;digest=hashlib.sha256(source).hexdigest()
        index={'views':[dict(id='NATIVE',label='Synthetic check / 厨房平面图',kind='elevation',document_id=document_id,page=1,region=[0.,0.,1.,1.])]}
        inventory=build_inventory([dict(id=document_id,local_path=str(artifacts['source']),sha256=digest)],index)
        catalog=build_automatic_catalog(inventory)
        grouped=[ident for group in catalog['groups'] for ident in group['native_ids']]
        original=[primitive['id'] for view in inventory['views'] for primitive in view['primitives']]
        check('packaged-automatic-native-group-coverage',len(grouped)==len(set(grouped))==len(original) and set(grouped)==set(original))
        check('packaged-autonomous-structured-schema',bool(strict_schema(AutonomousGroupSelection).get('properties')))
        check('packaged-autonomous-2d-review-rules','R09' in RULES and 'R12' in RULES and MAX_REQUESTS==36)
        check('packaged-reference-proposal-schema','estimates' in strict_schema(ReferencePlan).get('properties',{}))
        check('packaged-fresh-group-resolution-schema','group_resolutions' in strict_schema(ReviewReport).get('properties',{}))
        check('packaged-reference-only-amendment-schema','reference_only' in strict_schema(SourceScopeReview).get('properties',{}))
        prompt_dir=Path(__file__).with_name('prompts')
        check('packaged-autonomous-prompts',all((prompt_dir/f'autonomous_2d_{name}.md').is_file() and
              (prompt_dir/f'autonomous_2d_{name}.md').stat().st_size>200 for name in ('index','scope','extract','select','references','check')))
        check('packaged-native-path-extraction',bool(inventory['views'][0]['primitives']))
        check('packaged-native-clip-extraction',any(p['clips'] for p in inventory['views'][0]['primitives']))
        check('packaged-native-diagonal-text',any(p['text']=='3 1/2"' and abs(p['rotation']+45)<.01 for p in inventory['views'][0]['primitives']))
        check('packaged-native-chinese-text',any(p['text']=='木柜' for p in inventory['views'][0]['primitives']))
        model=StudioModel(name='Synthetic release check',parameters=[Parameter(id='GLOBAL_X',status='tbc'),
            Parameter(id='THICKNESS',status='tbc'),Parameter(id='WIDTH',status='source',value_mm=600.)],
            root=Part(id='ROOT',name='Project',children=[Part(id='ROOM',name='Unplaced synthetic room',position=['GLOBAL_X',0.,0.],
                children=[Part(id='FACE',name='Known source front',authority='source',surface=SourceSurface(plane='front',width='WIDTH',span=800.))])]),
            views=[SourceView(id='NATIVE',label='Synthetic native source check',kind='elevation',document_id=document_id,page=1,region=[0.,0.,1.,1.],include=['ROOM'])],requires_source_drawings=True)
        view=compile_drawings(inventory,dict(views=[dict(view_id='NATIVE',default_owner_id='ROOM')]),
                              {'GLOBAL_X':None,'THICKNESS':None,'WIDTH':600.})[0]
        view.semantic_snapshot=semantic_fingerprint(model)
        # This is a deterministic synthetic test receipt, not customer-drawing acceptance.
        view=stamp_review(view,True);model.drawings=[view]
        vector=render_pdf(view);artifacts['drawing'].write_bytes(vector)
        artifacts['preview'].write_bytes(render_png(view));artifacts['vectors'].write_text(render_svg(view),encoding='utf8')
        extracted=PdfReader(io.BytesIO(vector)).pages[0].extract_text() or ''
        check('packaged-vector-pdf-text','600mm' in ''.join(extracted.split()))
        check('packaged-chinese-pdf-text','厨房平面图' in extracted and '木柜' in extracted)
        chinese=next(p for p in view.primitives if p.kind=='text' and p.text=='木柜')
        preview=Image.open(io.BytesIO(artifacts['preview'].read_bytes())).convert('L')
        box=chinese.bbox;patch=preview.crop((int((box[0]+24)*3),int((box[1]+36)*3),int((box[2]+24)*3),int((box[3]+36)*3)))
        density=sum(patch.histogram()[:80])/max(1,patch.width*patch.height)
        check('packaged-chinese-glyph-rendering',.01<density<.45)
        with pdfium.PdfDocument(vector) as pdf:
            page=pdf[0]
            try:check('packaged-vector-pdf-paths',any(obj.type==raw.FPDF_PAGEOBJ_PATH for obj in page.get_objects()))
            finally:page.close()
        check('packaged-preview-png',artifacts['preview'].read_bytes().startswith(b'\x89PNG'))
        scene=build_scene(model,'synthetic-runtime',1)
        check('packaged-source-drawing-review-binding',scene['drawing_quality']['status']=='ready' and view.review_hash==drawing_hash(view))
        check('packaged-unplaced-world-remains-empty',not scene['meshes'] and 'GLOBAL_X' not in scene['resolved'])
        frame=scene['local_frames'].get('ROOM',{})
        check('packaged-local-frame-source-surface',len(frame.get('meshes',[]))==1 and frame['meshes'][0]['representation']=='source_surface' and not frame['global_placement_known'])
        payload={'schema':'vwc-studio-project/1','name':model.name,
            'documents':[dict(id=document_id,name='Synthetic-native-source.pdf',asset='sources/synthetic.pdf',sha256=digest)],
            'history':[dict(revision=1,model=model.model_dump_json(),summary='Synthetic packaging verification only.',created_at='2000-01-01T00:00:00+00:00')]}
        with zipfile.ZipFile(artifacts['fixture'],'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('project.json',json.dumps(payload,ensure_ascii=False));archive.writestr('sources/synthetic.pdf',source)
        report={'passed':True,'checks':checks,'artifacts':{k:str(v) for k,v in artifacts.items()},
                'paid_api_calls':0,'browser_opened':False,'authority':'Synthetic deterministic release check only; no customer drawing is approved.'}
        result=0
    except Exception as error:
        report={'passed':False,'checks':checks,'error_type':type(error).__name__,'paid_api_calls':0,'browser_opened':False}
        result=1
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    return result
