"""Read-only access to actual saved working images, without granting approval."""
from pathlib import Path
import hashlib
import json
import os
import re
from tempfile import NamedTemporaryFile
from urllib.parse import quote


def _run_folder(repository, job):
    if not isinstance(job.get('id'),str) or '.' not in job['id'] or not job.get('project_id'):return None
    project_id=job['project_id'];token=job['id'].split('.',1)[1]
    if project_id!=job['id'].split('.',1)[0] or not re.fullmatch(r'[a-f0-9]{32}',token):return None
    return repository.directory(project_id)/'workflow-runs'/token


def _result_at(folder, job, artifact_id=None, group=None):
    kind='3d' if job.get('kind') in ('generate3d','edit3d') else '2d'
    manifests=[folder/'3d'/'workflow-3d.json'] if kind=='3d' else [folder/f'cycle-{cycle}-working-result.json' for cycle in (2,1)]
    for manifest in manifests:
        try:
            if not manifest.is_file() or manifest.stat().st_size>1024*1024:continue
            record=json.loads(manifest.read_text(encoding='utf-8'))
            source=record.get('artifacts',[])
            if not isinstance(source,list) or len(source)>100:continue
            if kind=='3d':
                source=[a for a in source if a.get('kind')=='actual_3d_png']
                requested=re.fullmatch(r'3d-([12])-[A-Za-z0-9_.-]+\.png',artifact_id or '')
                cycle=int(requested.group(1)) if requested else max((int(a['artifact_id'].split('-')[1]) for a in source),default=0)
                source=[a for a in source if int(a['artifact_id'].split('-')[1])==cycle]
            else:cycle=record['cycle']
            if cycle not in (1,2):continue
            declared=record.get('views',[])
            if not isinstance(declared,list) or len(declared)>12:continue
            labels={v['view_id']:str(v['label'])[:200] for v in declared}
            if len(labels)!=len(declared):continue
            entries={};by_view={}
            for artifact in source:
                ident=artifact['artifact_id'];suffix=Path(ident).suffix
                if (not re.fullmatch(r'[A-Za-z0-9_.-]{1,200}',ident) or suffix not in ('.png','.pdf')
                        or not re.fullmatch(r'[a-f0-9]{64}',artifact['sha256'])):raise ValueError('Invalid working artifact')
                if kind=='3d' and suffix!='.png':raise ValueError('A working 3D camera must be a PNG')
                path=Path(artifact['path']);path=path if path.is_absolute() else manifest.parent/path
                path=path.resolve()
                if path.parent!=manifest.parent.resolve() or path.name!=ident or not path.is_file():
                    raise ValueError('Working artifact is not an owned saved file')
                if path.stat().st_size>100*1024*1024:raise ValueError('Working artifact too large')
                if ident in entries:raise ValueError('Duplicate working artifact')
                entries[ident]={'path':path,'sha256':artifact['sha256'],'suffix':suffix}
                view_id=artifact['view_id'];view=by_view.setdefault(view_id,{'view_id':view_id,'label':labels.get(view_id,str(view_id))})
                field='preview_url' if suffix=='.png' else 'pdf_url'
                if field in view:raise ValueError('Duplicate working output for one view')
                routed_id=group['id']+'--'+ident if group else ident
                view[field]=_artifact_url(job, routed_id)
            if not by_view or len(by_view)>12 or any('preview_url' not in view for view in by_view.values()):continue
            if kind=='2d' and (set(by_view)!=set(labels) or any('pdf_url' not in view for view in by_view.values())):continue
            if kind=='3d' and set(by_view)!={'AXON','PLAN','FRONT','RIGHT'}:continue
            if group and kind == '2d':
                for view in by_view.values():
                    pdf_id = view['pdf_url'].rsplit('/', 1)[-1].removeprefix(group['id'] + '--')
                    copied_from, copies = _copied_entries(entries[pdf_id])
                    for ident, entry in copies.items():
                        entries[ident] = entry
                        key = 'copied_pdf_url' if entry['suffix'] == '.pdf' else 'copied_preview_url'
                        view[key] = _artifact_url(job, group['id'] + '--' + ident)
                    if copies:
                        view['copied_from_project'] = copied_from
            if artifact_id is not None and artifact_id not in entries:continue
            state=group['status'] if group else job['status']
            status='ready' if state=='ready' else 'stopped' if state in ('cancelled','failed') else 'needs_review' if state=='needs_review' else 'checking'
            return {'kind':kind,'cycle':cycle,'checked':False,'status':status,'view_count':len(by_view),'views':list(by_view.values())},entries
        except (OSError,ValueError,KeyError,TypeError,IndexError):continue
    return None,{}


def _artifact_url(job, artifact_id):
    return '/api/studio/jobs/'+quote(job['id'],safe='')+'/working-results/'+quote(artifact_id,safe='')


def _copied_manifest(pdf):
    return pdf['path'].with_name('copied-' + pdf['path'].stem + '.json')


def _copied_entries(pdf):
    manifest = _copied_manifest(pdf)
    try:
        if not manifest.is_file() or manifest.stat().st_size > 32 * 1024 or manifest.resolve().parent != manifest.parent:
            return '', {}
        record = json.loads(manifest.read_text(encoding='utf-8'))
        name = record['copied_from_project']
        if (record.get('schema') != 'studio-copied-working-view/1' or record['base_pdf_sha256'] != pdf['sha256']
                or not isinstance(name, str) or not 1 <= len(name) <= 120 or set(record['artifacts']) != {'.png', '.pdf'}):
            return '', {}
        entries = {}
        for suffix, digest in record['artifacts'].items():
            if not re.fullmatch(r'[a-f0-9]{64}', digest):
                return '', {}
            ident = f'{manifest.stem}-{digest[:20]}{suffix}'
            path = (manifest.parent / ident).resolve()
            if path.parent != manifest.parent or path.name != ident or not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
                return '', {}
            entries[ident] = {'path': path, 'sha256': digest, 'suffix': suffix}
        return name, entries
    except (OSError, ValueError, KeyError, TypeError):
        return '', {}


def _publish_bytes(path, content):
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix='.copied-', delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _retained_view(repository, job, group_id, view_id):
    result, entries = working_result(repository, job)
    view = next((view for view in (result or {}).get('views', [])
                 if view['view_id'] == group_id + '--' + view_id), None)
    if view is None:
        raise ValueError('The retained working drawing could not be found')
    return view, entries


def copy_working_view(repository, job, group_id, view_id, donor_job, donor_group_id, donor_view_id, donor_name, evidence):
    view, entries = _retained_view(repository, job, group_id, view_id)
    donor_view, _ = _retained_view(repository, donor_job, donor_group_id, donor_view_id)
    pdf = entries[view['pdf_url'].rsplit('/', 1)[-1]]
    manifest = _copied_manifest(pdf)
    sources = {'.pdf': donor_view['pdf_url'], '.png': donor_view['preview_url']}
    content_by_format = {suffix: read_working_artifact(repository, donor_job, url.rsplit('/', 1)[-1])[0]
                         for suffix, url in sources.items()}
    hashes = {}
    for suffix, content in content_by_format.items():
        digest = hashlib.sha256(content).hexdigest()
        hashes[suffix] = digest
        _publish_bytes(manifest.parent / f'{manifest.stem}-{digest[:20]}{suffix}', content)
    record = {'schema': 'studio-copied-working-view/1', 'job_id': job['id'], 'view_id': view_id,
              'base_pdf_sha256': pdf['sha256'], 'copied_from_project': donor_name, 'source_job_id': donor_job['id'],
              'source_view_id': donor_view_id, 'source_view': evidence, 'source_review_status': donor_view['status'],
              'artifacts': hashes}
    _publish_bytes(manifest, (json.dumps(record, indent=2) + '\n').encode('utf-8'))
    return _retained_view(repository, job, group_id, view_id)[0]


def _owned_group_directory(runs_root, token, group_id):
    if not isinstance(token,str) or not re.fullmatch(r'[a-f0-9]{32}',token):return None
    run=(runs_root/token).resolve()
    directory=(run/'groups'/group_id).resolve()
    if run.parent==runs_root and directory.parent==run/'groups':
        return directory


def _group_paths(folder, job):
    runs_root=folder.parent.resolve()
    for group in job.get('groups_2d',[])[:4]:
        group_id=group.get('id','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',group_id):continue
        source_directory=_owned_group_directory(runs_root,group.get('source_run_id',folder.name),group_id)
        tokens=group.get('artifact_run_ids') or [folder.name]
        directories=[directory for token in reversed(tokens)
                     if (directory:=_owned_group_directory(runs_root,token,group_id)) is not None]
        if source_directory is not None and directories:
            yield group,source_directory,directories


def source_group_links(job):
    """Advertise only evidence pinned to this job's discovered groups."""
    groups=[]
    for group in job.get('groups_2d',[]):
        row=group.copy()
        if job['status'] in ('failed','cancelled') and row['status'] in ('queued','running'):
            row['status']='cancelled'
        for key,filename in (('source_map','source-map.png'),('source_evidence','source-evidence.json')):
            if re.fullmatch(r'[a-f0-9]{64}',row.get(key+'_sha256') or ''):
                row[key+'_url']=_artifact_url(job,row['id']+'--'+filename)
        groups.append(row)
    return groups


def working_result(repository, job, artifact_id=None):
    folder=_run_folder(repository, job)
    if folder is None:return None,{}
    if 'groups_2d' not in job:return _result_at(folder, job, artifact_id)
    views=[];entries={};latest=None
    for group,_,directories in _group_paths(folder, job):
        prefix=group['id']+'--'
        if artifact_id and not artifact_id.startswith(prefix):continue
        original_id=artifact_id.removeprefix(prefix) if artifact_id else None
        for directory in directories:
            result,original_entries=_result_at(directory,job,original_id,group)
            if result is not None:break
        if result is None:continue
        latest=result
        entries.update({prefix+key:value for key,value in original_entries.items()})
        views.extend(view | {'view_id':prefix+view['view_id'],'group_id':group['id'],'group_label':group['label'],
            'cycle':result['cycle'],'status':result['status']} for view in result['views'])
    if latest is None:return None,{}
    return latest | {'view_count':len(views),'views':views},entries


def read_working_artifact(repository,job,artifact_id):
    evidence_types={
        'source-map.png': ('source_map_sha256', 'image/png', b'\x89PNG\r\n\x1a\n'),
        'source-evidence.json': ('source_evidence_sha256', 'application/json', b'{'),
    }
    evidence_name=artifact_id.rsplit('--',1)[-1]
    if '--' in artifact_id and evidence_name in evidence_types and 'groups_2d' in job:
        key,media,signature=evidence_types[evidence_name]
        folder=_run_folder(repository,job)
        for group,directory,_ in _group_paths(folder,job) if folder else ():
            if artifact_id!=group['id']+'--'+evidence_name:continue
            digest=group.get(key) or ''
            if not re.fullmatch(r'[a-f0-9]{64}',digest):continue
            names=('initial-source-evidence.json', evidence_name) if evidence_name=='source-evidence.json' else (evidence_name,)
            for name in names:
                path=(directory/name).resolve()
                if path.parent==directory and path.is_file() and path.stat().st_size<=10*1024*1024:
                    blob=path.read_bytes()
                    if blob.startswith(signature) and hashlib.sha256(blob).hexdigest()==digest:
                        return blob,media
            if evidence_name=='source-evidence.json':
                source_run=directory.parent.parent
                source_job=job | {'id':job['project_id']+'.'+source_run.name}
                recovered=_recover_initial_evidence(source_run,source_job,group)
                if recovered is not None and hashlib.sha256(recovered).hexdigest()==digest:
                    return recovered,media
        raise ValueError('Source correspondence evidence is not available')
    result,entries=working_result(repository,job,artifact_id)
    if result is None or artifact_id not in entries:raise ValueError('Working output is not available')
    artifact=entries[artifact_id];blob=artifact['path'].read_bytes()
    if hashlib.sha256(blob).hexdigest()!=artifact['sha256']:raise ValueError('Working output changed after it was saved')
    signature=b'\x89PNG\r\n\x1a\n' if artifact['suffix']=='.png' else b'%PDF'
    if not blob.startswith(signature):raise ValueError('Working output has an invalid file format')
    return blob,'image/png' if artifact['suffix']=='.png' else 'application/pdf'


def _recover_initial_evidence(folder, job, group):
    """Reproduce a preview-build receipt only when the pinned hash proves exact bytes."""
    from .grouped_2d import source_evidence_record
    from .repository import encode

    discovery=(folder/'discovery'/'drawing-groups.json').resolve()
    if discovery.parent.parent!=folder.resolve() or not discovery.is_file() or discovery.stat().st_size>2*1024*1024:
        return None
    try:
        metadata=json.loads(discovery.read_text(encoding='utf-8'))
        if metadata.get('schema')!='formtopart-drawing-group-discovery/1':
            return None
        record=source_evidence_record(project_id=job['project_id'],job_id=job['id'],group_id=group['id'],
            label=group['label'],source_set_sha256=metadata['source_set_sha256'],
            source_views=group['source_views'],source_map_sha256=group['source_map_sha256'])
        return (encode(record)+'\n').encode('utf-8')
    except (KeyError, TypeError, ValueError, OSError):
        return None
