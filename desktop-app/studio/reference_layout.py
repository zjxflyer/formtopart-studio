"""One deterministic customer-reference dimension layout for PDF and SVG.

Reference graphics are an annotation layer. They never add physical edges to
the original native inventory or establish source-confirmed measurements.
"""
from __future__ import annotations

BLUE='#2563eb'
YELLOW='#fff1a6'
REFERENCE_LAYOUT_VERSION='anchor-connected-partitions-v3-inline-caption'
DIMENSION_LANE_CLEARANCE=8.


def reference_annotations(view):
    return sorted(getattr(view,'reference_annotations',[]) or [],key=lambda item:(item.orientation,item.control_id,item.estimate_id))


def reference_extents(view):
    graphics=reference_graphics(view);right=view.width;bottom=view.height
    for item in graphics['lines']:
        x1,y1,x2,y2=item['points'];right=max(right,x1,x2);bottom=max(bottom,y1,y2)
    for item in graphics['labels']:
        half_w=item['width']/2+4.;half_h=item['font']/2+3.
        if item['rotation']:half_w,half_h=half_h,half_w
        right=max(right,item['x']+half_w);bottom=max(bottom,item['y']+half_h)
    return max(0.,right-view.width+8.) if graphics['labels'] else 0.,max(0.,bottom-view.height+8.) if graphics['labels'] else 0.


def paper_layout(view, note_height=0):
    extra_width,extra_height=reference_extents(view)
    return {'width':view.width+48.+extra_width,'height':view.height+86.+extra_height+note_height,
        'origin':[24.,36.],'reference_width':extra_width,'reference_height':extra_height,'note_height':note_height}


import copy
import hashlib
import json
import math
import threading
from collections import OrderedDict,defaultdict


_REFERENCE_LAYOUT_CACHE=OrderedDict()
_REFERENCE_LAYOUT_CACHE_LOCK=threading.Lock()
_REFERENCE_LAYOUT_CACHE_LIMIT=8


def _merge(intervals):
    result=[]
    for a,b in sorted((float(a),float(b)) for a,b in intervals):
        if b-a<=1e-8:continue
        if result and a<=result[-1][1]+1e-8:result[-1][1]=max(result[-1][1],b)
        else:result.append([a,b])
    return result


def _intersect(first,second):
    return _merge((max(a,c),min(b,d)) for a,b in first for c,d in second if max(a,c)<min(b,d))


def _subtract(first,second):
    result=list(first)
    for c,d in second:
        next_result=[]
        for a,b in result:
            if d<=a or c>=b:next_result.append([a,b]);continue
            if a<c:next_result.append([a,c])
            if d<b:next_result.append([d,b])
        result=next_result
    return result


def _bounds(paths):
    points=[point for path in paths for point in path]
    return [min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)] if points else [0.,0.,0.,0.]


def _overlap(a,b):return a[0]<b[2] and b[0]<a[2] and a[1]<b[3] and b[1]<a[3]


def _segment_box_hit(points,box):
    """Exact segment/box slabs avoid rejecting a clear diagonal leader's bbox."""
    low,high=0.,1.
    for axis in (0,1):
        start=points[axis];delta=points[axis+2]-start;a=box[axis]-.3;b=box[axis+2]+.3
        if abs(delta)<1e-12:
            if not a<=start<=b:return False
        else:
            left,right=sorted(((a-start)/delta,(b-start)/delta));low=max(low,left);high=min(high,right)
            if low>high:return False
    return True


def _distance(point,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    t=0. if dx*dx+dy*dy==0 else max(0.,min(1.,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy)))
    return math.hypot(point[0]-a[0]-t*dx,point[1]-a[1]-t*dy)


def _crossing(a,b,c,d):
    dx,dy=b[0]-a[0],b[1]-a[1];ex,ey=d[0]-c[0],d[1]-c[1];den=dx*ey-dy*ex
    if abs(den)<1e-12:return None
    t=((c[0]-a[0])*ey-(c[1]-a[1])*ex)/den;u=((c[0]-a[0])*dy-(c[1]-a[1])*dx)/den
    return t if 0<=t<=1 and 0<=u<=1 else None


def _segment_distance(a,b,c,d):
    if _crossing(a,b,c,d) is not None:return 0.
    return min(_distance(a,c,d),_distance(b,c,d),_distance(c,a,b),_distance(d,a,b))


def _capsule_intervals(a,b,c,d,radius):
    """Candidate parameters inside the finite stroked source segment's band.

    Splitting at the endpoint projections makes each distance test quadratic.
    In particular, this checks visible stroke edges even when a later mask
    covers their centerline.
    """
    dx,dy=b[0]-a[0],b[1]-a[1];ex,ey=d[0]-c[0],d[1]-c[1];length=ex*ex+ey*ey
    projection=(a[0]-c[0])*ex+(a[1]-c[1])*ey;slope=dx*ex+dy*ey
    cuts={0.,1.}
    if length and abs(slope)>1e-12:
        cuts.update(t for t in (-projection/slope,(length-projection)/slope) if 0<t<1)
    ordered=sorted(cuts);result=[]
    for left,right in zip(ordered,ordered[1:]):
        mid=(left+right)/2;at=projection+mid*slope
        if not length or at<0 or at>length:
            endpoint=c if not length or at<0 else d
            px,py=a[0]-endpoint[0],a[1]-endpoint[1]
            aa=dx*dx+dy*dy;bb=2*(px*dx+py*dy);cc=px*px+py*py-radius*radius
        else:
            cross=ex*(a[1]-c[1])-ey*(a[0]-c[0]);change=ex*dy-ey*dx
            aa=change*change/length;bb=2*cross*change/length;cc=cross*cross/length-radius*radius
        if aa<1e-16:
            if cc<=0:result.append([left,right])
            continue
        determinant=bb*bb-4*aa*cc
        if determinant<0:continue
        root=math.sqrt(max(0.,determinant));lo=max(left,(-bb-root)/(2*aa));hi=min(right,(-bb+root)/(2*aa))
        if lo<hi:result.append([lo,hi])
    return _merge(result)


class _Ink:
    """Visible native display-list ink; routing never changes source commands."""
    def __init__(self,view):
        from .customer_references import _flatten,_inside
        self.inside=_inside;self.width=view.width;self.height=view.height;self.items=[];self.nodes=[];self.rays={};self.parts_cache={};self.components={};self.datums={};self.source_anchors={}
        for primitive in view.primitives:
            if primitive.role=='texture':continue  # Customer renderers do not paint this layer.
            row=primitive.model_dump();paths=_flatten(row['commands']) if row['kind']=='path' else []
            clips=[(_flatten(clip['commands']),clip['fill_rule']) for clip in row['clips']]
            item={'row':row,'paths':paths,'clips':clips,'box':_bounds(paths) if paths else row['bbox']}
            item['physical']=row['kind']=='path' and row['role'] in ('geometry','context') and ((row['stroke'] and row['stroke_color']!='white') or row['fill']=='black')
            index=len(self.items);self.items.append(item)
            if item['physical']:
                for path_index,path in enumerate(paths):
                    source_id=(row['source_ids'][path_index] if len(paths)==len(row['source_ids']) else
                               row['source_id'] if not row['source_ids'] else None)
                    if len(path)>1:self.nodes.append({'index':index,'path':path,'box':_bounds([path]),'source_id':source_id})
        self.links=defaultdict(list)
        for index,node in enumerate(self.nodes):
            for point in (node['path'][0],node['path'][-1]):
                if self.visible(point,node['index']):self.links[self.key(point)].append(index)

    @staticmethod
    def key(point):return tuple(round(value,7) for value in point)

    def clipped(self,point,item):return all(self.inside(point,paths,rule) for paths,rule in item['clips'])

    def visible(self,point,index):
        if not 0<=point[0]<=self.width or not 0<=point[1]<=self.height:return False
        if not self.clipped(point,self.items[index]):return False
        for later in self.items[index+1:]:
            row=later['row'];box=later['box'];radius=row['stroke_width']/2
            if not box[0]-radius<=point[0]<=box[2]+radius or not box[1]-radius<=point[1]<=box[3]+radius:continue
            if not self.clipped(point,later):continue
            if row['kind']=='path' and row['fill']!='none' and self.inside(point,later['paths'],row['fill_rule'],boundary=False):return False
            if row['kind']=='path' and row['stroke'] and row['stroke_color']=='white' and any(_distance(point,a,b)<=radius for path in later['paths'] for a,b in zip(path,path[1:])):return False
        return True

    def fill(self,paths,rule,axis,fixed,boundary=True):
        limit=self.width if axis==0 else self.height;cuts={0.,limit}
        for path in paths:
            for a,b in zip(path,path[1:]+path[:1]):
                d=b[1-axis]-a[1-axis]
                if abs(d)>1e-12:
                    t=(fixed-a[1-axis])/d
                    if 0<=t<=1:cuts.add(max(0.,min(limit,a[axis]+t*(b[axis]-a[axis]))))
                elif abs(fixed-a[1-axis])<=1e-9:cuts.update(max(0.,min(limit,p[axis])) for p in (a,b))
        ordered=sorted(cuts);result=[]
        for a,b in zip(ordered,ordered[1:]):
            point=[0.,0.];point[axis]=(a+b)/2;point[1-axis]=fixed
            if self.inside(point,paths,rule,boundary=boundary):result.append([a,b])
        return _merge(result)

    @staticmethod
    def stroke(paths,radius,axis,fixed):
        intervals=[]
        for path in paths:
            for a,b in zip(path,path[1:]):
                da=b[axis]-a[axis];db=b[1-axis]-a[1-axis]
                if not min(a[1-axis],b[1-axis])-radius<=fixed<=max(a[1-axis],b[1-axis])+radius:continue
                if abs(db)<=1e-12:
                    if abs(fixed-a[1-axis])<=radius:intervals.append([min(a[axis],b[axis])-radius,max(a[axis],b[axis])+radius])
                else:
                    center=a[axis]+(fixed-a[1-axis])*da/db;half=radius*math.hypot(da,db)/abs(db)
                    left=max(min(a[axis],b[axis])-radius,center-half);right=min(max(a[axis],b[axis])+radius,center+half)
                    if left<right:intervals.append([left,right])
                for endpoint in (a,b):
                    distance=abs(fixed-endpoint[1-axis])
                    if distance<radius:
                        half=math.sqrt(max(0.,radius*radius-distance*distance));intervals.append([endpoint[axis]-half,endpoint[axis]+half])
        return _merge(intervals)

    def ray(self,axis,fixed,physical=False):
        key=(axis,round(fixed,8),physical)
        if key in self.rays:return self.rays[key]
        if not 0<=fixed<=(self.height if axis==0 else self.width):return []
        limit=self.width if axis==0 else self.height;result=[]
        for item in self.items:
            row=item['row'];box=item['box'];radius=row['stroke_width']/2
            if not box[1-axis]-radius<=fixed<=box[3-axis]+radius:continue
            clips=[[0.,limit]]
            for paths,rule in item['clips']:clips=_intersect(clips,self.fill(paths,rule,axis,fixed))
            if not clips:continue
            if row['kind']=='text':
                if not physical:result=_merge([*result,*_intersect([[box[axis],box[axis+2]]],clips)])
                continue
            fill=_intersect(self.fill(item['paths'],row['fill_rule'],axis,fixed,boundary=False),clips) if row['fill']!='none' else []
            stroke=_intersect(self.stroke(item['paths'],radius,axis,fixed),clips) if row['stroke'] else []
            result=_subtract(result,fill)
            if row['stroke_color']=='white':result=_subtract(result,stroke)
            if not physical or item['physical']:
                ink=([*fill] if row['fill']=='black' else [])+([*stroke] if row['stroke_color']!='white' else [])
                result=_merge([*result,*ink])
        self.rays[key]=result;return result

    def box_hit(self,box):
        for axis,fixed,left,right in ((0,box[1],box[0],box[2]),(0,box[3],box[0],box[2]),(1,box[0],box[1],box[3]),(1,box[2],box[1],box[3]),(0,(box[1]+box[3])/2,box[0],box[2])):
            if any(a<right and left<b for a,b in self.ray(axis,fixed)):return True
        for item in self.items:
            if not _overlap(item['box'],box):continue
            candidates=([((item['box'][0]+item['box'][2])/2,(item['box'][1]+item['box'][3])/2)] if item['row']['kind']=='text' else [p for path in item['paths'] for p in path])
            for point in candidates:
                if box[0]<point[0]<box[2] and box[1]<point[1]<box[3] and any(a<=point[0]<=b for a,b in self.ray(0,point[1])):return True
        return False

    def line_hit(self,points):
        x1,y1,x2,y2=points
        if abs(y2-y1)<1e-8:return any(a<max(x1,x2) and min(x1,x2)<b for a,b in self.ray(0,y1))
        if abs(x2-x1)<1e-8:return any(a<max(y1,y2) and min(y1,y2)<b for a,b in self.ray(1,x1))
        a,b=[x1,y1],[x2,y2];box=[min(x1,x2)-.25,min(y1,y2)-.25,max(x1,x2)+.25,max(y1,y2)+.25]
        for index,item in enumerate(self.items):
            row=item['row'];radius=row['stroke_width']/2+.25
            bounds=[item['box'][0]-radius,item['box'][1]-radius,item['box'][2]+radius,item['box'][3]+radius]
            if not _overlap(box,bounds):continue
            if row['kind']=='text':
                if _segment_box_hit(points,item['box']):
                    # A native word box is a conservative glyph envelope, but
                    # its empty off-diagonal corners are not obstacles.
                    cuts={0.,1.};l,t,r,s=item['box'];path=[(l,t),(r,t),(r,s),(l,s),(l,t)]
                    for c,d in zip(path,path[1:]):
                        hit=_crossing(a,b,c,d)
                        if hit is not None:cuts.add(hit)
                    for left,right in zip(sorted(cuts),sorted(cuts)[1:]):
                        q=(left+right)/2;p=(x1+q*(x2-x1),y1+q*(y2-y1))
                        if l<=p[0]<=r and t<=p[1]<=s and self.visible(p,index):return True
                continue
            if row['stroke'] and row['stroke_color']!='white':
                for path in item['paths']:
                    for c,d in zip(path,path[1:]):
                        edge=[min(c[0],d[0])-radius,min(c[1],d[1])-radius,max(c[0],d[0])+radius,max(c[1],d[1])+radius]
                        if not _overlap(box,edge):continue
                        for left,right in _capsule_intervals(a,b,c,d,radius):
                            p=[x1+left*(x2-x1),y1+left*(y2-y1)];q=[x1+right*(x2-x1),y1+right*(y2-y1)]
                            if self.segment_parts(p,q,index):return True
            if row['fill']=='black':
                for left,right in self.segment_parts(a,b,index):
                    point=((left[0]+right[0])/2,(left[1]+right[1])/2)
                    if self.inside(point,item['paths'],row['fill_rule']):return True
        return False

    def segment_parts(self,a,b,index):
        """Visible centerline pieces after source canvas, clips and paint masks."""
        key=(index,tuple(a),tuple(b))
        if key in self.parts_cache:return self.parts_cache[key]
        item=self.items[index];bounds=_bounds([[a,b]])
        boundaries=[[(0.,0.),(self.width,0.),(self.width,self.height),(0.,self.height),(0.,0.)]]
        boundaries += [path for paths,_ in item['clips'] for path in paths]
        if item['row']['fill']!='none':boundaries+=item['paths']
        cuts={0.,1.}
        for later in self.items[index+1:]:
            if later['row']['kind']=='path' and later['row']['fill']!='none' and _overlap(bounds,later['box']):
                boundaries+=later['paths'];boundaries += [p for paths,_ in later['clips'] for p in paths]
            if later['row']['kind']=='path' and later['row']['stroke'] and later['row']['stroke_color']=='white':
                radius=later['row']['stroke_width']/2
                for path in later['paths']:
                    for c,d in zip(path,path[1:]):
                        for left,right in _capsule_intervals(a,b,c,d,radius):cuts.update((left,right))
                boundaries += [p for paths,_ in later['clips'] for p in paths]
        for path in boundaries:
            for c,d in zip(path,path[1:]+path[:1]):
                hit=_crossing(a,b,c,d)
                if hit is not None:cuts.add(hit)
        ordered=sorted(cuts);result=[];dx=b[0]-a[0];dy=b[1]-a[1]
        for left,right in zip(ordered,ordered[1:]):
            mid=(left+right)/2
            if self.visible((a[0]+mid*dx,a[1]+mid*dy),index):result.append([(a[0]+q*dx,a[1]+q*dy) for q in (left,right)])
        self.parts_cache[key]=result;return result

    def extension(self,points,labels=()):
        """Gap a NEW extension at existing annotation ink, never physical ink."""
        x,y,u,v=points;axis=0 if abs(y-v)<1e-8 else 1;fixed=y if axis==0 else x
        start=points[axis];end=points[axis+2];low,high=sorted((start,end))
        physical=self.ray(axis,fixed,True)
        if any(a<high and low<b for a,b in physical):return None
        annotation=_subtract(self.ray(axis,fixed),physical)
        prior=[]
        for label in labels:
            box=_label_box(label,2.)
            if box[1-axis]<fixed<box[3-axis]:
                interval=_intersect([[low,high]],[[box[axis]-1.5,box[axis+2]+1.5]])
                for a,b in interval:prior.append({'control_id':label['control_id'],'numeric':label['numeric'],'interval':[a,b]})
        gaps=_intersect([[low,high]],_merge([*((a-1.5,b+1.5) for a,b in annotation),*(row['interval'] for row in prior)]))
        visible=_subtract([[low,high]],gaps)
        if not visible or max(b-a for a,b in visible)<2.:return None
        if end<start:visible=list(reversed(visible))
        def segment(a,b):return [a,fixed,b,fixed] if axis==0 else [fixed,a,fixed,b]
        pieces=[segment(a,b) if end>=start else segment(b,a) for a,b in visible]
        return pieces,[segment(a,b) for a,b in gaps],[{**row,'points':segment(*row['interval'])} for row in prior]

    def collinear_datum(self,axis,fixed,anchor):
        """Prove retained visible collinear source ink connected to the anchor.

        This proves a native ink chain, not that two named semantic datums are
        interchangeable. The fresh source review still owns that decision.
        """
        key=(axis,round(fixed,8))
        if key not in self.datums:
            rows=[]
            for index,item in enumerate(self.items):
                row=item['row']
                if not item['physical'] or not row['stroke'] or row['stroke_color']=='white':continue
                radius=row['stroke_width']/2
                for path_index,path in enumerate(item['paths']):
                    source=(row['source_ids'][path_index] if len(item['paths'])==len(row['source_ids']) else
                            row['source_id'] if not row['source_ids'] else None)
                    for a,b in zip(path,path[1:]):
                        if abs(a[1-axis]-fixed)>1e-6 or abs(b[1-axis]-fixed)>1e-6:continue
                        for p,q in self.segment_parts(a,b,index):
                            interval=[min(p[axis],q[axis])-radius,max(p[axis],q[axis])+radius]
                            for left,right in _intersect([interval],self.ray(axis,fixed)):
                                rows.append({'interval':[left,right],'source_id':source,'retained_primitive_id':row['id'],'owner_id':row['owner_id']})
            self.datums[key]=rows
        rows=self.datums[key]
        connected=next((interval for interval in _merge(r['interval'] for r in rows)
            if interval[0]-1e-7<=anchor<=interval[1]+1e-7),None)
        evidence=[r for r in rows if connected and r['interval'][0]<connected[1] and connected[0]<r['interval'][1]]
        return connected,evidence

    def witness(self,anchor,points,labels=()):
        """Partition the ideal projection; never discard free ink before a wall."""
        x,y,u,v=points;axis=0 if abs(y-v)<1e-8 else 1;fixed=y if axis==0 else x
        start=points[axis];end=points[axis+2];sign=1. if end>=start else -1.
        low,high=sorted((start,end));whole=[[low,high]]
        native=self.ray(axis,fixed);physical=self.ray(axis,fixed,True)
        connected,evidence=self.collinear_datum(axis,fixed,anchor[axis])
        continuation=_intersect(whole,[connected]) if connected else []
        opaque=_subtract(_intersect(whole,physical),continuation)
        annotation=_subtract(_intersect(whole,native),_merge([*continuation,*opaque]))
        prior=[]
        for label in labels:
            box=_label_box(label,2.)
            if box[1-axis]<fixed<box[3-axis]:
                for a,b in _intersect(whole,[[box[axis]-1.5,box[axis+2]+1.5]]):
                    prior.append({'control_id':label['control_id'],'numeric':label['numeric'],'interval':[a,b]})
        annotation_gaps=_intersect(whole,_merge([*((a-1.5,b+1.5) for a,b in annotation),*(r['interval'] for r in prior)]))
        # Clearance belongs to the actual connected contour, even when its
        # painted half-width ends just before the ideal three-point start.
        datum_clearance=_intersect(whole,[[connected[0]-3.,connected[1]+3.]]) if connected else []
        hidden=_merge([*datum_clearance,*((a-.35,b+.35) for a,b in opaque),*annotation_gaps])
        visible=_subtract(whole,hidden)
        if not visible or max(b-a for a,b in visible)<2.:return None
        if sign<0:visible=list(reversed(visible))
        def segment(a,b):return [a,fixed,b,fixed] if axis==0 else [fixed,a,fixed,b]
        pieces=[segment(a,b) if sign>0 else segment(b,a) for a,b in visible]
        first=pieces[0][axis]
        prefix=(max(0.,connected[1]-anchor[axis]) if sign>0 else max(0.,anchor[axis]-connected[0])) if connected else 0.
        # A remote tail behind an unrelated opaque object cannot alone establish
        # attachment. Retain near-anchor ink or an evidenced native continuation.
        before_first=_intersect([[min(start,first),max(start,first)]],opaque)
        physical_chain=next((interval for interval in physical if interval[0]-1e-7<=anchor[axis]<=interval[1]+1e-7),None)
        key=self.key(anchor)
        if key not in self.source_anchors:
            self.source_anchors[key]=[{'retained_primitive_id':self.items[node['index']]['row']['id'],
                'source_id':node['source_id']} for node in self.nodes
                if any(abs(p[0]-anchor[0])<1e-7 and abs(p[1]-anchor[1])<1e-7 for p in node['path'])
                and self.visible(anchor,node['index'])]
        anchor_evidence=self.source_anchors[key]
        # Underlay is supported only by an unbroken actually painted interval
        # connected to a still-visible source contour vertex. A blank prefix
        # before a remote wall is not native continuation or occlusion proof.
        occluded_prefix=bool(anchor_evidence and physical_chain and
            ((sign>0 and physical_chain[1]+.350001>=first) or
             (sign<0 and physical_chain[0]-.350001<=first)))
        if abs(first-start)>6. and prefix<3. and sum(b-a for a,b in before_first)>2. and not occluded_prefix:return None
        return {'segments':pieces,'gaps':[segment(a,b) for a,b in annotation_gaps],
            'reference_label_gaps':[{**r,'points':segment(*r['interval'])} for r in prior],
            'native_collinear_datum_continuation':[segment(a,b) for a,b in continuation],
            'physical_occlusion_intervals':[segment(a,b) for a,b in opaque],
            'source_annotation_gaps':[segment(a,b) for a,b in annotation],
            'true_anchor':list(anchor),'ideal_projection':[anchor[0],anchor[1],u,v],
            'ideal_projection_start':points[:2],'first_visible_start':pieces[0][:2],
            'true_physical_start':pieces[0][:2],
            'source_continuation_proof':{'connected_native_interval':connected,'source_segments':evidence,
                'semantic_datum_equivalence_requires_fresh_review':True},
            'physical_prefix_connected_to_visible_source_anchor':occluded_prefix,
            'source_anchor_proof':anchor_evidence if occluded_prefix else [],
            'connected_physical_prefix_interval':physical_chain if occluded_prefix else None,
            'association_basis':('retained_collinear_native_datum' if prefix>=3. else
                'retained_opaque_source_ink_from_visible_anchor' if occluded_prefix else 'visible_near_anchor_projection'),
            'gap_basis':'source_annotation_and_prior_reference_labels' if prior else 'existing_nonphysical_source_annotation_ink'}


    def component_box(self,ref):
        # This index is scoped to one immutable layout call. Reuse across its
        # bounded packing orders without retaining view state across renders.
        key=id(ref)
        if key in self.components:return self.components[key]
        anchors=(ref.point_a,ref.point_b);seeds=[]
        bound=ref.provenance.get('anchors',[])
        for ordinal,point in enumerate(anchors):
            provenance=bound[ordinal] if len(bound)==2 else None
            for index,node in enumerate(self.nodes):
                box=node['box'];row=self.items[node['index']]['row']
                if provenance is not None:
                    if row['id']!=provenance.get('retained_primitive_id'):continue
                    if node['source_id'] is not None and node['source_id']!=provenance.get('source_primitive_id'):continue
                if (box[0]-.3<=point[0]<=box[2]+.3 and box[1]-.3<=point[1]<=box[3]+.3 and
                    self.visible(point,node['index']) and any(_distance(point,a,b)<.3 for a,b in zip(node['path'],node['path'][1:]))):seeds.append(index)
        preferred=[index for index in seeds if self.items[self.nodes[index]['index']]['row']['owner_id']==ref.owner_id]
        if preferred:seeds=preferred
        seed_owners={self.items[self.nodes[index]['index']]['row']['owner_id'] for index in seeds}
        seen=set(seeds);queue=list(seeds)
        while queue and len(bound)!=2:
            node=self.nodes[queue.pop()]
            for point in (node['path'][0],node['path'][-1]):
                for other in self.links[self.key(point)]:
                    if other not in seen and self.items[self.nodes[other]['index']]['row']['owner_id'] in seed_owners:
                        seen.add(other);queue.append(other)
        points=[tuple(point) for point in anchors]
        for index in seen:
            node=self.nodes[index];item=self.items[node['index']]
            boundaries=[[(0.,0.),(self.width,0.),(self.width,self.height),(0.,self.height),(0.,0.)]]
            boundaries += [path for paths,_ in item['clips'] for path in paths]
            for later in self.items[node['index']+1:]:
                if later['row']['kind']=='path' and later['row']['fill']!='none' and _overlap(node['box'],later['box']):boundaries+=later['paths']
            for a,b in zip(node['path'],node['path'][1:]):
                cuts={0.,1.};dx=b[0]-a[0];dy=b[1]-a[1]
                for path in boundaries:
                    for c,d in zip(path,path[1:]+path[:1]):
                        ex=d[0]-c[0];ey=d[1]-c[1];den=dx*ey-dy*ex
                        if abs(den)<1e-12:continue
                        t=((c[0]-a[0])*ey-(c[1]-a[1])*ex)/den;u=((c[0]-a[0])*dy-(c[1]-a[1])*dx)/den
                        if 0<=t<=1 and 0<=u<=1:cuts.add(t)
                ordered=sorted(cuts)
                for left,right in zip(ordered,ordered[1:]):
                    mid=(left+right)/2
                    if self.visible((a[0]+mid*dx,a[1]+mid*dy),node['index']):points.extend([(a[0]+t*dx,a[1]+t*dy) for t in (left,right)])
        box=_bounds([points]);self.components[key]=box;return box


def _main_lanes_collide(candidate,placed):
    def spans(rows):
        result={}
        for row in rows:
            if row['kind']!='dimension':continue
            x,y,u,v=row['points'];vertical=abs(x-u)<1e-8
            lane=x if vertical else y;low,high=sorted((y,v) if vertical else (x,u))
            key=(row['control_id'],vertical,lane)
            old=result.get(key,[low,high]);result[key]=[min(old[0],low),max(old[1],high)]
        return result
    # Include the intentional numeric-label break in a control's full span.
    # Opposite-end labels must not let two nearly coincident controls through.
    for (control,vertical,lane),first in spans(candidate).items():
        for (other,other_vertical,other_lane),second in spans(placed).items():
            if control==other or vertical!=other_vertical:continue
            if abs(lane-other_lane)<DIMENSION_LANE_CLEARANCE and max(first[0],second[0])<min(first[1],second[1]):return True
    return False


def _label_box(label,pad=0.):
    w=label['width']/2+(3. if label['numeric'] else 0.)+pad;h=label['font']/2+(2. if label['numeric'] else 0.)+pad
    if label['rotation']:w,h=h,w
    return [label['x']-w,label['y']-h,label['x']+w,label['y']+h]


def _line_box(row):
    x,y,u,v=row['points'];return [min(x,u)-.3,min(y,v)-.3,max(x,u)+.3,max(y,v)+.3]


def _caption_parts(text,span,string_width):
    """Keep descriptive captions close by wrapping, rather than sliding away."""
    maximum=min(100.,max(60.,span));parts=[];line=''
    for word in text.split():
        candidate=(line+' '+word).strip()
        if line and string_width(candidate,'Helvetica',7.)>maximum:parts.append(line);line=word
        else:line=candidate
        while string_width(line,'Helvetica',7.)>maximum:
            cut=1
            while cut<len(line) and string_width(line[:cut+1],'Helvetica',7.)<=maximum:cut+=1
            parts.append(line[:cut]);line=line[cut:]
    if line:parts.append(line)
    return parts


class _NoLane(ValueError):pass


def _reference_graphics(view,ordering=0,priority=(),ink=None):
    """Resolve clear local lanes; true anchors never become drawn extension starts."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    refs=reference_annotations(view)
    if not refs:return {'lines':[],'labels':[],'records':[]}
    ink=ink if ink is not None else _Ink(view);lines=[];labels=[];records=[];occupied=[]
    ordered=sorted(refs,key=lambda r:(min(r.point_a[1],r.point_b[1]),min(r.point_a[0],r.point_b[0]),r.control_id))
    if ordering:
        def span(ref):return abs(ref.point_b[1 if ref.orientation=='vertical' else 0]-ref.point_a[1 if ref.orientation=='vertical' else 0])
        if ordering<=2:ordered=sorted(ordered,key=lambda ref:((1 if ordering==1 else -1)*span(ref),ref.control_id))
        else:ordered=sorted(ordered,key=lambda ref:(ref.orientation!=('horizontal' if ordering==3 else 'vertical'),span(ref),ref.control_id))
    if priority:
        ranks={ident:index for index,ident in enumerate(priority)}
        ordered=sorted(ordered,key=lambda ref:ranks.get(ref.control_id,len(ranks)))
    for ref in ordered:
        a,b=list(ref.point_a),list(ref.point_b);vertical=ref.orientation=='vertical';axis=0 if vertical else 1
        box=ink.component_box(ref);low,high=sorted((a[1-axis],b[1-axis]));mid=(low+high)/2
        value=f'{ref.value_mm:.3f}'.rstrip('0').rstrip('.')+' mm';font=9.;width=stringWidth(value,'Helvetica',font);gap=width/2+4.
        caption_parts=_caption_parts(ref.label,high-low,stringWidth);accepted=None;rejections=defaultdict(int)
        positions=[(1,o) for o in (12.,8.,20.,28.,36.,44.,52.,60.)]+[(-1,o) for o in (12.,8.,20.,28.,36.,44.,52.,60.)]+[(1,68.+n*12.) for n in range(32)]
        def placement_cost(position):
            sign,offset=position;lane=box[axis+2]+offset if sign>0 else box[axis]-offset
            cost=max(abs(lane-point[axis]) for point in (a,b))
            for point in (a,b):
                low_ray,high_ray=sorted((point[axis],lane))
                blockers=_intersect([[low_ray,high_ray]],ink.ray(axis,point[1-axis],True))
                connected,_=ink.collinear_datum(axis,point[1-axis],point[axis])
                opaque=_subtract(blockers,[connected] if connected else [])
                cost+=sum(right-left for left,right in opaque)*3.+len(opaque)*6.
            return cost
        positions=sorted(positions,key=placement_cost)
        natural_short=high-low<2*gap or abs(max(gap+5.,mid)-mid)>.1
        modes=[('high',1.),('high',-1.),('low',1.),('low',-1.),('center',1.),('center',-1.)] if natural_short else [('center',1.),('high',1.),('high',-1.),('low',1.),('low',-1.)]
        for sign,offset,mode,numeric_sign,numeric_distance in [(s,o,m,n,d) for s,o in positions for m,n in modes for d in ((2.,14.,26.) if m!='center' else (2.,))]:
            lane=box[axis+2]+offset if sign>0 else box[axis]-offset
            if lane<5.:continue
            candidate=[]
            def line(x1,y1,x2,y2,kind):candidate.append({'points':[float(x1),float(y1),float(x2),float(y2)],'kind':kind,'control_id':ref.control_id,'estimate_id':ref.estimate_id})
            center=max(gap+5.,mid);short=high-low<2*gap or abs(center-mid)>.1;side=lane+sign*14. if short else lane
            alternate=mode!='center'
            if alternate:
                short=True;center=high+gap+8. if mode=='high' else low-gap-8.;side=lane+numeric_sign*numeric_distance
            elif short:side=lane+numeric_sign*14.
            if vertical:
                if short:line(lane,low,lane,high,'dimension');line(lane,mid,side-numeric_sign*4. if not alternate else side,center if not alternate else center+(-gap if mode=='high' else gap),'leader')
                else:line(lane,low,lane,mid-gap,'dimension');line(lane,mid+gap,lane,high,'dimension')
                numeric={'x':side,'y':center,'text':value,'rotation':-90.,'font':font,'numeric':True,'width':width,'control_id':ref.control_id}
            else:
                if short:line(low,lane,high,lane,'dimension');line(mid,lane,center-4. if not alternate else center+(-gap if mode=='high' else gap),side,'leader')
                else:line(low,lane,mid-gap,lane,'dimension');line(mid+gap,lane,high,lane,'dimension')
                numeric={'x':center,'y':side,'text':value,'rotation':0.,'font':font,'numeric':True,'width':width,'control_id':ref.control_id}
            starts=[];valid=True
            for anchor in (a,b):
                start=anchor[axis]+sign*3.
                if sign*(lane-start)<2.:valid=False;break
                point=list(anchor);point[axis]=start;starts.append(point)
                if vertical:line(start,anchor[1],lane+sign*4.,anchor[1],'extension');line(lane-2.5,anchor[1]+2.5,lane+2.5,anchor[1]-2.5,'tick')
                else:line(anchor[0],start,anchor[0],lane+sign*4.,'extension');line(anchor[0]-2.5,lane+2.5,anchor[0]+2.5,lane-2.5,'tick')
            if not valid:rejections['witness_clearance']+=1;continue
            if _main_lanes_collide(candidate,lines):rejections['parallel_dimension_lane_crowding']+=1;continue
            routed=[];witness_gaps=[]
            for row in candidate:
                if row['kind']!='extension':routed.append(row);continue
                result=ink.witness((a,b)[len(witness_gaps)],row['points'],labels)
                if result is None:valid=False;break
                pieces=result['segments']
                for part,points in enumerate(pieces):routed.append({**row,'points':points,'kind':'extension' if part==0 else 'extension_continuation'})
                witness_gaps.append(result)
            if not valid:rejections['physical_witness_or_empty_gap']+=1;continue
            starts=[witness['first_visible_start'] for witness in witness_gaps]
            candidate=routed
            blocked=[row['kind'] for row in candidate if ink.line_hit(row['points'])]
            if blocked:
                for kind in set(blocked):rejections['native_'+kind]+=1
                continue
            if any(_segment_box_hit(row['points'],other) for row in candidate for other in occupied):rejections['prior_label']+=1;continue
            numeric_box=_label_box(numeric,2.)
            if min(numeric_box)<0 or ink.box_hit(numeric_box) or any(_overlap(numeric_box,b) for b in occupied) or any(_segment_box_hit(row['points'],numeric_box) for row in lines):rejections['numeric_label']+=1;continue
            # Source titles/scales can enclose a clear numeric lane while both
            # perpendicular caption bands are occupied. Try two bounded inline
            # alternatives beyond this dimension's complete ink/label extent;
            # every existing native/prior-label/leader collision check still runs.
            measure=1-axis
            half=max(stringWidth(text,'Helvetica',7.) for text in caption_parts)/2+2.
            along_low=min(numeric_box[measure],*(min(row['points'][measure],row['points'][measure+2]) for row in candidate))
            along_high=max(numeric_box[measure+2],*(max(row['points'][measure],row['points'][measure+2]) for row in candidate))
            inline_shifts=(along_high+8.+half-numeric['y' if vertical else 'x'],
                           along_low-8.-half-numeric['y' if vertical else 'x'])
            for caption_side,extra in [*[(side,extra) for side in (sign,-sign) for extra in (0.,6.,12.)],(0.,0.)]:
                for shift in inline_shifts if caption_side==0. else (0.,12.,-12.,24.,-24.):
                    captions=[];extent=(len(caption_parts)-1)*9./2+3.5
                    perpendicular=(numeric['x'] if vertical else numeric['y'])+caption_side*(6.5+5.+extent+extra)
                    for index,text in enumerate(caption_parts):
                        across=perpendicular+(index-(len(caption_parts)-1)/2)*9.
                        captions.append({'x':across if vertical else numeric['x']+shift,
                            'y':numeric['y']+shift if vertical else across,'text':text,'full_text':ref.label,
                            'rotation':-90. if vertical else 0.,'font':7.,'numeric':False,
                            'width':stringWidth(text,'Helvetica',7.),'control_id':ref.control_id})
                    caption_box=[min(_label_box(c,2.)[0] for c in captions),min(_label_box(c,2.)[1] for c in captions),
                                 max(_label_box(c,2.)[2] for c in captions),max(_label_box(c,2.)[3] for c in captions)]
                    if min(caption_box)<0 or ink.box_hit(caption_box) or _overlap(caption_box,numeric_box) or any(_overlap(caption_box,b) for b in occupied):continue
                    if any(_segment_box_hit(row['points'],caption_box) for row in [*lines,*candidate]):continue
                    accepted=(candidate,numeric,captions,starts,lane,witness_gaps);break
                if accepted:break
            if accepted:break
            rejections['caption']+=1
        if accepted is None:
            error=_NoLane('Reference dimension '+ref.control_id+' has no clear lane within the bounded local annotation layout')
            error.rejections=dict(rejections);error.control_id=ref.control_id;raise error
        candidate,numeric,captions,starts,lane,witness_gaps=accepted
        lines.extend(candidate);labels.extend([numeric,*captions]);occupied.extend([_label_box(numeric,2.),*[_label_box(c,2.) for c in captions]])
        records.append({'estimate_id':ref.estimate_id,'control_id':ref.control_id,'true_anchor_points':[a,b],'drawn_extension_starts':starts,'orientation':ref.orientation,'lane':lane,'label':value,'numeric_background':YELLOW,'reference_only':True,'routing_basis':'visible anchor-connected physical paths and projected witness rays','witness_routing':witness_gaps})
    return {'lines':lines,'labels':labels,'records':records}


def _resolve_reference_graphics(view):
    """Use bounded deterministic packing orders; never waive a collision."""
    if not reference_annotations(view):return {'lines':[],'labels':[],'records':[]}
    ink=_Ink(view)
    failure=None
    for ordering in range(5):
        try:return _reference_graphics(view,ordering,ink=ink)
        except _NoLane as error:failure=error
    priority=[];seen=set()
    for _ in range(4):
        priority=[failure.control_id,*[ident for ident in priority if ident!=failure.control_id]]
        if tuple(priority) in seen:break
        seen.add(tuple(priority))
        try:return _reference_graphics(view,priority=priority,ink=ink)
        except _NoLane as error:failure=error
    raise failure


def reference_graphics(view):
    """Reuse only exactly bound successful layouts; callers own returned data.

    Source paint, clips, provenance and references all participate in identity.
    Review receipts do not change graphics. No failed layout is cached, and a
    private snapshot prevents later caller mutation from altering stored data.
    """
    if not reference_annotations(view):return {'lines':[],'labels':[],'records':[]}
    snapshot=view.model_copy(deep=True)
    content=snapshot.model_dump(mode='json',exclude={'review_status','review_issues','review_hash'})
    identity=json.dumps([REFERENCE_LAYOUT_VERSION,content],sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
    key=hashlib.sha256(identity.encode('utf-8')).digest()
    with _REFERENCE_LAYOUT_CACHE_LOCK:
        cached=_REFERENCE_LAYOUT_CACHE.get(key)
        if cached is not None:
            _REFERENCE_LAYOUT_CACHE.move_to_end(key)
            return copy.deepcopy(cached)
    result=_resolve_reference_graphics(snapshot)
    with _REFERENCE_LAYOUT_CACHE_LOCK:
        _REFERENCE_LAYOUT_CACHE[key]=copy.deepcopy(result)
        _REFERENCE_LAYOUT_CACHE.move_to_end(key)
        while len(_REFERENCE_LAYOUT_CACHE)>_REFERENCE_LAYOUT_CACHE_LIMIT:_REFERENCE_LAYOUT_CACHE.popitem(last=False)
    return result
