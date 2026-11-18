import { useEffect, useLayoutEffect, useRef, useState, type PointerEvent } from 'react';
import { studioAPI } from './api';
import { t } from './i18n';
import type { ReferenceDemoManifest } from './types';

/** Fit the original standalone viewer chrome into a shared project viewport. */
export function compactEmbeddedReference(frame: HTMLIFrameElement): boolean {
  try {
    const document = frame.contentDocument; if (!document?.head || !document.body) return false;
    document.body.dataset.formtopartEmbedded = 'true';
    let style = document.getElementById('formtopart-embedded-layout') as HTMLStyleElement | null;
    if (!style) { style = document.createElement('style'); style.id = 'formtopart-embedded-layout'; document.head.append(style); }
    style.textContent = `html{height:100%!important;min-height:0!important;overflow:hidden!important}body[data-formtopart-embedded]{height:100%!important;min-height:0!important;margin:0!important;display:flex!important;flex-direction:column!important;overflow:hidden!important}body[data-formtopart-embedded]>header{display:none!important}body[data-formtopart-embedded] #controls{flex:none!important;gap:3px!important;padding:4px 5px!important;font-size:10px!important;line-height:1.2!important}body[data-formtopart-embedded] #controls button,body[data-formtopart-embedded] #controls select{font-size:10px!important;padding:3px 5px!important;line-height:1.2!important;min-height:22px!important}body[data-formtopart-embedded] #controls label{font-size:10px!important;gap:2px!important;line-height:1.2!important}body[data-formtopart-embedded] #controls .sp-selection-status{font-size:9px!important;line-height:1.2!important;max-height:24px;overflow:auto}body[data-formtopart-embedded] #controls select[aria-label^="Appearance"]{display:none!important}body[data-formtopart-embedded] #viewer{flex:1 1 80px!important;height:auto!important;min-height:80px!important;max-height:none!important;overflow:hidden!important}body[data-formtopart-embedded] #fallback{flex:1 1 80px!important;min-height:0!important;overflow:auto!important}body[data-formtopart-embedded] #note{flex:none!important;font-size:9px!important;line-height:1.2!important;padding:2px 6px!important}`;
    const view = frame.contentWindow;
    view?.requestAnimationFrame(() => view.dispatchEvent(new Event('resize')));
    return true;
  } catch { return false; }
}

/** Use the original viewer's own display control without replacing its scene or camera. */
export function setEmbeddedAppearance(frame: HTMLIFrameElement, appearance: 'outline' | 'material'): boolean {
  try {
    const control = frame.contentDocument?.querySelector<HTMLSelectElement>('select[aria-label^="Appearance"]');
    if (!control || !Array.from(control.options).some(option => option.value === appearance)) return false;
    if (control.value !== appearance) { control.value = appearance; const event = frame.contentDocument!.createEvent('Event'); event.initEvent('change', true, false); control.dispatchEvent(event); }
    return true;
  } catch { return false; }
}

const DRAWING_PADDING = 20;

function DrawingImage({ src, title, zoom }: { src: string; title: string; zoom: number }) {
  const frame = useRef<HTMLDivElement>(null);
  const host = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ width: 900, height: 620 });
  const [aspect, setAspect] = useState(1.35); const [failed, setFailed] = useState(false);
  const pan = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  useLayoutEffect(() => {
    const element = frame.current; if (!element) return;
    const measure = () => {
      // Measure the bounded outer frame, never the scrollbar-sensitive inner scroller.
      const bounds = element.getBoundingClientRect();
      const width = Math.floor(bounds.width - DRAWING_PADDING * 2) - 2, height = Math.floor(bounds.height - DRAWING_PADDING * 2) - 2;
      if (width > 0 && height > 0) setBox(previous => previous.width === width && previous.height === height ? previous : { width, height });
    };
    measure();
    const observer = new ResizeObserver(measure); observer.observe(element, { box: 'border-box' });
    return () => observer.disconnect();
  }, []);
  useEffect(() => { setFailed(false); if (host.current) { host.current.scrollTop = 0; host.current.scrollLeft = 0; } }, [src]);
  useEffect(() => { if (zoom === 1 && host.current) { host.current.scrollTop = 0; host.current.scrollLeft = 0; } }, [zoom]);
  const width = Math.min(box.width, box.height / aspect) * zoom;
  function startPan(event: PointerEvent<HTMLDivElement>) {
    if (zoom <= 1 || event.button !== 0 || (event.target as Element).closest('button,a')) return;
    pan.current = { x: event.clientX, y: event.clientY, left: event.currentTarget.scrollLeft, top: event.currentTarget.scrollTop };
    event.currentTarget.setPointerCapture?.(event.pointerId); event.preventDefault();
  }
  return <div ref={frame} className="reference-drawing-frame"><div ref={host} className={`reference-drawing-stage ${zoom > 1 ? 'zoomed' : ''}`} style={{ padding: DRAWING_PADDING, overflow: zoom > 1 ? 'auto' : 'hidden' }} onPointerDown={startPan}
    onPointerMove={event => { if (pan.current) { event.currentTarget.scrollLeft = pan.current.left - event.clientX + pan.current.x; event.currentTarget.scrollTop = pan.current.top - event.clientY + pan.current.y; } }}
    onPointerUp={() => { pan.current = null; }} onPointerCancel={() => { pan.current = null; }} onLostPointerCapture={() => { pan.current = null; }}>
    {failed ? <div className="reference-view-error" role="alert"><p>{t('This drawing could not load.', '图纸未能加载。')}</p><button className="secondary" onClick={() => setFailed(false)}>{t('Try again', '重试')}</button></div>
      : <div className="reference-drawing-canvas" style={{ width, height: width * aspect }}><img src={src} alt={title} draggable={false} style={{ width, height: width * aspect }} onLoad={event => { const image = event.currentTarget; if (image.naturalWidth && image.naturalHeight) setAspect(previous => { const next = image.naturalHeight / image.naturalWidth; return previous === next ? previous : next; }); }} onError={() => setFailed(true)} /></div>}
  </div></div>;
}

type ReferenceControls = { manifest: ReferenceDemoManifest; sectionId: string; viewId: string; onSection: (id: string) => void; onView: (id: string) => void };

/** Contextual controls inside the same project toolbar used by every project. */
export function ReferenceViewTabs({ manifest, sectionId, viewId, onSection, onView }: ReferenceControls) {
  const section = manifest.sections.find(item => item.id === sectionId) || manifest.sections[0];
  if (!section) return null;
  return <><select className="reference-section-select" aria-label={t('Design section', '设计区域')} value={section.id} onChange={event => onSection(event.target.value)}>{manifest.sections.map(item => <option key={item.id} value={item.id}>{item.id} · {item.title}</option>)}</select>
    {section.views.map(item => <button role="tab" key={item.id} aria-selected={viewId === item.id} className={viewId === item.id ? 'active' : ''} title={item.label} onClick={() => onView(item.id)}>{item.label.split(' - ')[0]}</button>)}
    <button role="tab" aria-selected={viewId === '3d'} className={viewId === '3d' ? 'active' : ''} onClick={() => onView('3d')}>3D</button>
    <a className="subtle reference-pdf-link" href={section.pdf_url || studioAPI.referenceAsset(section.pdf)} download={`${section.id}-Reviewed-Drawings.pdf`}>{t('PDF', 'PDF')} ↗</a></>;
}

/** Literal approved drawing image or original HTML viewer, within the shared center viewport. */
export function ReferenceViewer({ manifest, sectionId, viewId, zoom, appearance = 'outline' }: { manifest: ReferenceDemoManifest; sectionId: string; viewId: string; zoom: number; appearance?: 'outline' | 'material' }) {
  const frame = useRef<HTMLIFrameElement>(null);
  useEffect(() => { if (frame.current) setEmbeddedAppearance(frame.current, appearance); }, [appearance, sectionId, viewId]);
  const [viewerReady, setViewerReady] = useState(false); const [viewerFailed, setViewerFailed] = useState(false); const [viewerAttempt, setViewerAttempt] = useState(0);
  const section = manifest.sections.find(item => item.id === sectionId) || manifest.sections[0];
  const drawing = section?.views.find(item => item.id === viewId) || section?.views[0];
  useEffect(() => { setViewerReady(false); setViewerFailed(false); }, [sectionId, viewId]);
  if (!section) return null;
  if (viewId !== '3d') return drawing ? <DrawingImage src={drawing.image_url || studioAPI.referenceAsset(drawing.image)} title={`${section.id} ${drawing.source_title || drawing.label}`} zoom={zoom} /> : null;
  return <div className="reference-3d-stage">{!viewerReady && !viewerFailed && <div className="reference-view-loading" role="status">{t('Loading 3D view…', '正在加载三维视图…')}</div>}{viewerFailed ? <div className="reference-view-error" role="alert"><p>{t('The 3D view could not load.', '三维视图未能加载。')}</p><button className="secondary" onClick={() => { setViewerFailed(false); setViewerReady(false); setViewerAttempt(value => value + 1); }}>{t('Try again', '重试')}</button></div> : <iframe ref={frame} key={`${section.id}:${viewerAttempt}`} className="reference-3d-viewer" title={`${section.id} ${section.title} 3D viewer`} src={section.viewer_url || studioAPI.referenceAsset(section.viewer_html)} sandbox="allow-scripts allow-same-origin allow-downloads" onLoad={event => { compactEmbeddedReference(event.currentTarget); setEmbeddedAppearance(event.currentTarget, appearance); setViewerReady(true); }} onError={() => setViewerFailed(true)} />}</div>;
}

/** Real packet/page navigation alongside original customer sources in the common Sources panel. */
export function ReferenceSourceList({ manifest, sectionId, viewId, onSelect }: {
  manifest: ReferenceDemoManifest; sectionId: string; viewId: string; onSelect: (section: string, view: string) => void;
}) {
  return <section className="source-map-list" aria-label={t('Reviewed drawing outputs', '已审阅设计图纸')}>
    {manifest.sections.flatMap(section => section.views.map((view, index) => {
      const selected = sectionId === section.id && viewId === view.id;
      return <button type="button" className={`source-map-card ${selected ? 'selected' : ''}`} key={JSON.stringify([section.id, view.id])}
        title={`${section.id} ${view.source_title || view.label}`} aria-current={selected || undefined} onClick={() => onSelect(section.id, view.id)}>
        <small className="document-kind">{t('REVIEWED OUTPUT', '已审阅成果')}</small>
        <span>{view.label}</span><small>{section.id} · P{view.source_page ?? view.page ?? index + 1}</small>
      </button>;
    }))}
  </section>;
}
