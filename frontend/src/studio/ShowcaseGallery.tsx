import { useEffect, useRef, useState, type PointerEvent } from 'react';
import { t } from './i18n';
import type { ShowcaseManifest } from './types';
import { studioAPI } from './api';

export function ShowcaseGallery({ manifest, onThreeD, zoom = 1 }: { manifest: ShowcaseManifest; onThreeD: () => void; zoom?: number }) {
  const [selected, setSelected] = useState(manifest.sheets[0]?.id || '');
  const [failed, setFailed] = useState(false);
  const [aspect, setAspect] = useState(1.35);
  const [box, setBox] = useState({ width: 600, height: 500 });
  const [panning, setPanning] = useState(false);
  const stage = useRef<HTMLDivElement>(null);
  const pan = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const current = manifest.sheets.find(sheet => sheet.id === selected) || manifest.sheets[0];
  const pdf = typeof manifest.reviewed_pdf_url === 'string' ? manifest.reviewed_pdf_url : manifest.reviewed_pdf ? studioAPI.showcaseAsset(manifest.reviewed_pdf) : '';
  useEffect(() => {
    const element = stage.current; if (!element) return;
    const measure = () => {
      const style = getComputedStyle(element);
      const width = element.clientWidth - (parseFloat(style.paddingLeft) || 0) - (parseFloat(style.paddingRight) || 0);
      const height = element.clientHeight - (parseFloat(style.paddingTop) || 0) - (parseFloat(style.paddingBottom) || 0);
      if (width > 0 && height > 0) setBox({ width, height });
    };
    const observer = new ResizeObserver(measure); observer.observe(element); measure();
    return () => observer.disconnect();
  }, []);
  const imageWidth = Math.min(box.width, box.height / aspect) * zoom;
  function selectSheet(id: string) {
    setSelected(id); setFailed(false);
    if (stage.current) { stage.current.scrollLeft = 0; stage.current.scrollTop = 0; }
  }
  function startPan(event: PointerEvent<HTMLDivElement>) {
    if (zoom <= 1 || event.button !== 0 || (event.target as Element).closest('button,a')) return;
    const element = event.currentTarget;
    pan.current = { x: event.clientX, y: event.clientY, left: element.scrollLeft, top: element.scrollTop };
    setPanning(true); element.setPointerCapture?.(event.pointerId); event.preventDefault();
  }
  function movePan(event: PointerEvent<HTMLDivElement>) {
    if (!pan.current) return;
    event.currentTarget.scrollLeft = pan.current.left - event.clientX + pan.current.x;
    event.currentTarget.scrollTop = pan.current.top - event.clientY + pan.current.y;
  }
  function endPan() { pan.current = null; setPanning(false); }
  return <section className="showcase-gallery" aria-label={t('Reviewed drawing gallery', '已审阅图纸集')}>
    <div className="showcase-gallery-heading"><div><span className="eyebrow">{t('REVIEWED DRAWING SET', '已审阅图纸集')}</span><h3>{t('Plans & elevations', '平面与立面图')}</h3><p>{t('Explore the plans, elevations and design details.', '查看平面、立面与设计细节。')}</p></div><div><button className="secondary" onClick={onThreeD}>{t('Back to 3D', '返回三维')}</button>{pdf && <a className="primary" href={pdf} download="Reviewed-Plans-and-Elevations.pdf">{t('Download drawing PDF', '下载图纸PDF')} ↗</a>}</div></div>
    <div className="showcase-gallery-body"><nav aria-label={t('Drawing sheets', '图纸页')}>
      {manifest.sheets.map((sheet, index) => <button key={sheet.id} className={current?.id === sheet.id ? 'active' : ''} onClick={() => selectSheet(sheet.id)} aria-current={current?.id === sheet.id ? 'page' : undefined}><span>{String(index + 1).padStart(2, '0')}</span><strong>{sheet.title}</strong></button>)}
    </nav><div ref={stage} className={`reviewed-sheet-stage ${zoom > 1 ? 'zoomed' : ''} ${panning ? 'panning' : ''}`} onPointerDown={startPan} onPointerMove={movePan} onPointerUp={endPan} onPointerCancel={endPan} onLostPointerCapture={endPan}>
      {current && !failed ? <div className="reviewed-sheet-canvas" style={{ width: Math.max(box.width, imageWidth), minHeight: Math.max(box.height, imageWidth * aspect) }}><img className="reviewed-sheet-image" src={current.image_url || studioAPI.showcaseAsset(current.image)} alt={current.title} draggable={false} style={{ width: imageWidth, height: imageWidth * aspect }} onLoad={event => { const image = event.currentTarget; if (image.naturalWidth && image.naturalHeight) setAspect(image.naturalHeight / image.naturalWidth); }} onError={() => setFailed(true)} /></div> : <div className="reviewed-sheet-error" role="alert"><p>{t('This drawing image could not load.', '此图纸图片未能加载。')}</p><button className="secondary" onClick={() => setFailed(false)}>{t('Try again', '重试')}</button>{pdf && <a href={pdf} download>{t('Download the complete PDF', '下载完整PDF')}</a>}</div>}
    </div></div>
    <div className="showcase-gallery-caption">{current?.title}<span>{t('Reference drawing · Original annotation units', '参考图纸 · 原始标注单位')}</span></div>
  </section>;
}
