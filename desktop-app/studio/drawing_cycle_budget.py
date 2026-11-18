"""Durable, serial two-cycle budget for one complete customer2D view group.

The caller supplies the same project-level path on every invocation. This is a
local workflow guard, not a credential store or a visual/fabrication certificate.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import time
import uuid

MAX_GROUP_CYCLES=2
OPERATIONS={'create_2d','repair_2d','corrective_2d','recompile_2d','manual_update_2d'}


class DrawingCycleError(ValueError):
    category='drawing_cycle_budget'


def _json(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def _hash(value):return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()
def _now():return datetime.now(timezone.utc).isoformat()
def _sha(value):return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)


class DrawingCycleBudget:
    def __init__(self,ledger_path,*,project_id,documents,required_views,lock_timeout=5.):
        if not project_id or not required_views:raise DrawingCycleError('A project and complete source-view manifest are required')
        self.path=Path(ledger_path).resolve();self.project_id=project_id;self.lock_timeout=lock_timeout
        self.active_lease_id=None;self.source_files=[];docs={};source_set=[]
        for item in documents:
            if item['id'] in docs or not _sha(item['sha256']) or not isinstance(item['page_count'],int) or item['page_count']<1:
                raise DrawingCycleError('Invalid source identity for the drawing-cycle group')
            path=Path(item['local_path']).resolve(strict=True)
            self.source_files.append((path,item['sha256']))
            docs[item['id']]={'sha256':item['sha256'],'page_count':item['page_count']}
            source_set.append(docs[item['id']])
        self._assert_sources()
        if not docs:raise DrawingCycleError('A nonempty source set is required')
        views=[];ids=set()
        for original in required_views:
            item=original.model_dump() if hasattr(original,'model_dump') else dict(original)
            if item['id'] in ids or item['document_id'] not in docs:raise DrawingCycleError('Duplicate view or unavailable source document')
            ids.add(item['id']);document=docs[item['document_id']];region=item['region']
            if not isinstance(item['page'],int) or not 1<=item['page']<=document['page_count']:
                raise DrawingCycleError('View page is outside the source document')
            if len(region)!=4 or any(not math.isfinite(x) for x in region) or not 0<=region[0]<region[2]<=1 or not 0<=region[1]<region[3]<=1:
                raise DrawingCycleError('View region must use normalized displayed-page coordinates')
            views.append({'id':item['id'],'source_sha256':document['sha256'],'page':item['page'],'kind':item['kind'],
                          'region':[float(x) for x in region]})
        self.sources=sorted({ _json(item):item for item in source_set}.values(),key=_json)
        self.views=sorted(views,key=_json)
        self.source_set_sha256=_hash(self.sources);self.view_set_sha256=_hash(self.views)
        self.group_key=_hash({'project_id':project_id,'sources':self.sources,'views':self.views})

    def _assert_sources(self):
        if any(hashlib.sha256(path.read_bytes()).hexdigest()!=digest for path,digest in self.source_files):
            raise DrawingCycleError('Source bytes changed; the existing drawing-cycle group cannot be reset')

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        lock=self.path.with_name(self.path.name+'.lock')
        with lock.open('a+b') as handle:
            if handle.seek(0,os.SEEK_END)==0:handle.write(b'0');handle.flush()
            deadline=time.monotonic()+self.lock_timeout
            while True:
                try:
                    handle.seek(0)
                    if os.name=='nt':
                        import msvcrt
                        msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                    break
                except OSError as error:
                    if time.monotonic()>=deadline:raise DrawingCycleError('Drawing-cycle ledger is busy; no request was reserved') from error
                    time.sleep(.025)
            try:yield
            finally:
                handle.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(),fcntl.LOCK_UN)

    def _new(self):
        return {'schema':'vwc-drawing-group-cycles/1','project_id':self.project_id,'group_key':self.group_key,
                'sources':self.sources,'views':self.views,'source_set_sha256':self.source_set_sha256,
                'view_set_sha256':self.view_set_sha256,'max_cycles':MAX_GROUP_CYCLES,'reserved_count':0,'cycles':[]}

    def _read(self):
        if not self.path.exists():return None
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            digest=data.pop('ledger_sha256')
            if digest!=_hash(data):raise DrawingCycleError('Drawing-cycle ledger integrity check failed')
            expected=set(self._new())
            if set(data)!=expected or data['schema']!='vwc-drawing-group-cycles/1' or data['max_cycles']!=MAX_GROUP_CYCLES:
                raise DrawingCycleError('Invalid drawing-cycle ledger schema or limit')
            if any(data[key]!=self._new()[key] for key in ('project_id','group_key','sources','views','source_set_sha256','view_set_sha256')):
                raise DrawingCycleError('Source/view scope drift cannot create a new drawing-cycle budget in this project ledger')
            cycles=data['cycles']
            if not isinstance(cycles,list) or type(data['reserved_count']) is not int or data['reserved_count']!=len(cycles) or len(cycles)>MAX_GROUP_CYCLES:
                raise DrawingCycleError('Invalid drawing-cycle counter')
            seen=set()
            for index,cycle in enumerate(cycles,1):
                if set(cycle)!={'number','lease_id','operation','reserved_at','metadata','state','candidate_sha256','review','failure'}:
                    raise DrawingCycleError('Invalid drawing-cycle record')
                if type(cycle['number']) is not int or cycle['number']!=index or cycle['lease_id'] in seen or not isinstance(cycle['lease_id'],str) or len(cycle['lease_id'])!=32:
                    raise DrawingCycleError('Drawing-cycle reservations are missing or duplicated')
                seen.add(cycle['lease_id'])
                if cycle['operation'] not in OPERATIONS or cycle['state'] not in ('reserved','candidate_ready','reviewed','failed'):
                    raise DrawingCycleError('Invalid drawing-cycle phase')
                if index==1 and cycle['operation']!='create_2d':raise DrawingCycleError('An initial drawing must establish the group')
                candidate=cycle['candidate_sha256'];review=cycle['review']
                if candidate is not None and not _sha(candidate):raise DrawingCycleError('Invalid candidate binding in drawing-cycle ledger')
                if cycle['state'] in ('candidate_ready','reviewed') and candidate is None:raise DrawingCycleError('Drawing-cycle candidate binding is missing')
                if cycle['state']=='reserved' and candidate is not None:raise DrawingCycleError('Reserved cycle cannot contain a published candidate')
                if review is not None:
                    if set(review)!={'candidate_sha256','artifacts_sha256','report_sha256','verdict','accepted','checked_at'}:
                        raise DrawingCycleError('Invalid drawing-cycle review record')
                    if review['candidate_sha256']!=candidate or any(not _sha(review[k]) for k in ('candidate_sha256','artifacts_sha256','report_sha256')):
                        raise DrawingCycleError('Drawing-cycle review does not bind the current candidate')
                    if type(review['accepted']) is not bool or (review['accepted'] and review['verdict'] not in ('PASS','PASS_WITH_LIMITS')):
                        raise DrawingCycleError('Invalid drawing-cycle acceptance record')
                if cycle['state']=='reviewed' and review is None:raise DrawingCycleError('Drawing-cycle review is missing')
                if cycle['state']!='reviewed' and review is not None:raise DrawingCycleError('Unfinished drawing cycle cannot retain acceptance')
                if index<len(cycles) and cycle['state'] not in ('reviewed','failed'):
                    raise DrawingCycleError('A subsequent drawing started before the previous cycle finished')
            return data
        except DrawingCycleError:raise
        except (OSError,ValueError,TypeError,KeyError) as error:
            raise DrawingCycleError('Drawing-cycle ledger is unreadable or corrupt; it cannot be reset') from error

    def _write(self,data):
        payload={**data,'ledger_sha256':_hash(data)}
        temporary=self.path.with_name(self.path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            with temporary.open('x',encoding='utf-8') as handle:
                handle.write(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False));handle.flush();os.fsync(handle.fileno())
            os.replace(temporary,self.path)
        finally:
            if temporary.exists():temporary.unlink()

    def reserve(self,operation,metadata=None):
        if operation not in OPERATIONS:raise DrawingCycleError('Only explicit drawing/correction operations reserve a cycle')
        metadata=json.loads(_json(metadata or {}))
        if len(_json(metadata))>8000:raise DrawingCycleError('Drawing-cycle metadata exceeds the bounded receipt size')
        self._assert_sources()
        with self._locked():
            data=self._read()
            if data is None:
                if operation!='create_2d':raise DrawingCycleError('A repair/correction cannot initialize a fresh drawing-cycle ledger')
                data=self._new()
            if len(data['cycles'])>=MAX_GROUP_CYCLES:raise DrawingCycleError('The complete2D view group has exhausted its TWO drawing cycles')
            if data['cycles'] and data['cycles'][-1]['state'] not in ('reviewed','failed'):
                raise DrawingCycleError('The previous drawing cycle must finish its check or fail before another update')
            lease={'number':len(data['cycles'])+1,'lease_id':uuid.uuid4().hex,'operation':operation,'reserved_at':_now(),
                'metadata':metadata,'state':'reserved','candidate_sha256':None,'review':None,'failure':None}
            data['cycles'].append(lease);data['reserved_count']=len(data['cycles']);self._write(data)
        self.active_lease_id=lease['lease_id'];return dict(lease)

    def _change(self,lease_id,apply):
        self._assert_sources()
        with self._locked():
            data=self._read()
            if data is None or not data['cycles'] or data['cycles'][-1]['lease_id']!=lease_id:
                raise DrawingCycleError('Only the latest bound drawing cycle may record an outcome')
            apply(data['cycles'][-1]);self._write(data)

    def mark_candidate(self,lease_id,candidate_sha256):
        if not _sha(candidate_sha256):raise DrawingCycleError('A complete candidate hash is required')
        def apply(cycle):
            if cycle['state']!='reserved':raise DrawingCycleError('A cycle cannot publish multiple changed candidates')
            cycle['candidate_sha256']=candidate_sha256;cycle['state']='candidate_ready'
        self._change(lease_id,apply)

    def note_review(self,lease_id,*,candidate_sha256,artifacts_sha256,report_sha256,verdict,accepted):
        if any(not _sha(value) for value in (candidate_sha256,artifacts_sha256,report_sha256)) or type(accepted) is not bool:
            raise DrawingCycleError('Review outcome requires exact candidate/artifact/report bindings')
        if accepted and verdict not in ('PASS','PASS_WITH_LIMITS'):raise DrawingCycleError('An unaccepted review cannot permit3D')
        def apply(cycle):
            if cycle['state']!='candidate_ready' or cycle['candidate_sha256']!=candidate_sha256:
                raise DrawingCycleError('Review does not belong to this cycle candidate')
            cycle['review']={'candidate_sha256':candidate_sha256,'artifacts_sha256':artifacts_sha256,
                'report_sha256':report_sha256,'verdict':verdict,'accepted':accepted,'checked_at':_now()}
            cycle['state']='reviewed';cycle['failure']=None
        self._change(lease_id,apply)

    def note_failure(self,lease_id,*,phase,category):
        def apply(cycle):
            if cycle['state'] not in ('reserved','candidate_ready'):
                raise DrawingCycleError('A terminal drawing-cycle outcome cannot be rewritten')
            cycle['state']='failed';cycle['review']=None
            cycle['failure']={'phase':str(phase)[:80],'category':str(category)[:80],'at':_now()}
        self._change(lease_id,apply)

    @staticmethod
    def _is_legacy_source_fallback(data):
        if data is None or not data['cycles']:
            return False
        for index, cycle in enumerate(data['cycles']):
            metadata = cycle['metadata']
            failure = cycle['failure']
            operation = 'repair_2d' if index else 'create_2d'
            if (cycle['operation'] != operation or cycle['state'] != 'failed'
                    or cycle['candidate_sha256'] is not None or cycle['review'] is not None
                    or not isinstance(metadata, dict) or set(metadata) != {'run_id', 'phase', 'api_drawing_sent'}
                    or not isinstance(metadata['run_id'], str) or not metadata['run_id']
                    or metadata['phase'] != 'unclassified_source_fallback' or metadata['api_drawing_sent'] is not False
                    or not isinstance(failure, dict) or set(failure) != {'phase', 'category', 'at'}
                    or failure['phase'] != 'grouping_native_sources' or failure['category'] != 'unclassified_source_fallback'
                    or not isinstance(failure['at'], str) or not failure['at']):
                return False
        return True

    def is_legacy_source_fallback(self):
        """Check whether all recorded leases were source-only diagnostics."""
        self._assert_sources()
        with self._locked():
            return self._is_legacy_source_fallback(self._read())

    def retire_legacy_source_fallback(self):
        """Preserve a legacy source-only diagnostic ledger before remapping its scope."""
        self._assert_sources()
        with self._locked():
            if not self._is_legacy_source_fallback(self._read()):
                return False
            digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
            history = self.path.with_name(f'{self.path.stem}.legacy-source-fallback-{digest}{self.path.suffix}')
            if history.exists() or history.is_symlink():
                raise DrawingCycleError('Legacy source diagnostic history already exists; the active ledger was kept.')
            # One same-directory rename keeps the original bytes and never exposes
            # a state where both the active ledger and its historical copy are missing.
            self.path.rename(history)
            self.active_lease_id = None
        return True

    def snapshot(self):
        self._assert_sources()
        with self._locked():data=self._read() or self._new()
        cycles=data['cycles'];latest=cycles[-1] if cycles else None
        accepted=bool(latest and latest['state']=='reviewed' and latest['review']['accepted'])
        return {'ledger_path':str(self.path),'project_id':self.project_id,'group_key':self.group_key,
            'max_cycles':MAX_GROUP_CYCLES,'cycles_used':len(cycles),'cycles_remaining':MAX_GROUP_CYCLES-len(cycles),
            'status':'accepted_2d' if accepted else ('exhausted_needs_review' if len(cycles)==MAX_GROUP_CYCLES else ('not_started' if not cycles else 'needs_review')),
            'can_start_drawing':len(cycles)<MAX_GROUP_CYCLES and (not latest or latest['state'] in ('reviewed','failed')),
            'can_start_3d':accepted,'latest_cycle':json.loads(_json(latest)) if latest else None,
            'cycles':json.loads(_json(cycles)),
            'ledger_sha256':_hash(data)}
