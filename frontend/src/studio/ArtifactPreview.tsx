import { useEffect, useId, useState, type ReactNode } from 'react';
import { StudioSheet } from './StudioSheet';
import { t } from './i18n';
import './artifact-preview.css';

export type StudioArtifact = { url: string; title: string } & (
  { kind: 'image' | 'json' } | { kind: 'pdf'; previewImageUrl: string }
);

export function ArtifactPreviewLink({ artifact, onPreview, children }: {
  artifact: StudioArtifact; onPreview: (artifact: StudioArtifact) => void; children: ReactNode;
}) {
  return <a href={artifact.url} aria-haspopup="dialog" onAuxClick={event => event.preventDefault()}
    onClick={event => {
      event.preventDefault();
      event.currentTarget.focus();
      onPreview(artifact);
    }}>{children}</a>;
}

export function ArtifactPreview({ artifact, onClose }: { artifact: StudioArtifact; onClose: () => void }) {
  const titleId = useId();
  const [jsonText, setJsonText] = useState<string>();
  const [failed, setFailed] = useState(false);
  const { kind, url } = artifact;
  useEffect(() => {
    if (kind !== 'json') return;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(url, { signal: controller.signal, mode: 'same-origin' });
        if (!response.ok) throw new Error('Artifact unavailable');
        const value: unknown = await response.json();
        if (!controller.signal.aborted) setJsonText(JSON.stringify(value, null, 2));
      } catch {
        if (!controller.signal.aborted) setFailed(true);
      }
    })();
    return () => controller.abort();
  }, [kind, url]);

  const downloadLabel = kind === 'pdf' ? t('Download PDF', '下载 PDF')
    : kind === 'json' ? t('Download JSON', '下载 JSON') : t('Download image', '下载图片');
  return <StudioSheet wide title={artifact.title} titleId={titleId} onClose={onClose}>
    <div className="artifact-preview">
      <div className="artifact-preview-actions">
        {kind === 'pdf' && <span>{t('Working drawing preview', '工作图纸预览')}</span>}
        <a href={url} className="secondary" download>{downloadLabel}</a>
      </div>
      {failed ? <p className="artifact-preview-message" role="alert">{t('This preview could not be opened.', '无法打开此预览。')}</p>
        : kind === 'json' ? jsonText === undefined
          ? <p className="artifact-preview-message" role="status">{t('Loading source evidence…', '正在加载原图定位依据…')}</p>
          : <pre tabIndex={0} aria-label={t('Source evidence JSON', '原图定位依据 JSON')}>{jsonText}</pre>
        : <div className="artifact-preview-image" tabIndex={0} role="region" aria-label={t('Image preview', '图片预览')}>
          <img src={kind === 'pdf' ? artifact.previewImageUrl : url}
            alt={kind === 'pdf' ? t('Working drawing preview', '工作图纸预览') : artifact.title} onError={() => setFailed(true)} />
        </div>}
    </div>
  </StudioSheet>;
}
