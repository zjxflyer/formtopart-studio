import { t } from './i18n';
import { useEffect, useRef, type ReactNode } from 'react';

/** One keyboard-contained sheet, restoring focus to the control that opened it. */
export function StudioSheet({ title, titleId, onClose, locked = false, wide = false, children }: {
  title: string; titleId: string; onClose: () => void; locked?: boolean; wide?: boolean; children: ReactNode;
}) {
  const dialog = useRef<HTMLDivElement>(null); const state = useRef({ locked, onClose });
  const composing = useRef(false); state.current = { locked, onClose };
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const panel = dialog.current;
    const controls = () => Array.from(panel?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],summary:not([tabindex="-1"]),[tabindex="0"]') || [])
      .filter(control => {
        const closedDetails = control.closest('details:not([open])');
        return !closedDetails || closedDetails.querySelector('summary') === control;
      });
    (panel?.querySelector<HTMLElement>('[data-autofocus]') || controls()[0] || panel)?.focus();
    function keyboard(event: KeyboardEvent) {
      if (composing.current || event.isComposing || event.keyCode === 229) return;
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); if (!state.current.locked) state.current.onClose(); }
      if (event.key !== 'Tab') return;
      const items = controls(), first = items[0], last = items.at(-1);
      if (!first || !last) { event.preventDefault(); panel?.focus(); }
      else if (!panel?.contains(document.activeElement)) { event.preventDefault(); first.focus(); }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    document.addEventListener('keydown', keyboard, true);
    return () => { document.removeEventListener('keydown', keyboard, true); if (opener?.isConnected) opener.focus(); };
  }, []);
  return <div className="studio-sheet-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !locked) onClose(); }}>
    <div ref={dialog} className={`studio-sheet ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
      onCompositionStartCapture={() => { composing.current = true; }} onCompositionEndCapture={() => { composing.current = false; }}
      onKeyDownCapture={event => { if (event.key === 'Enter' && (composing.current || event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229)) event.preventDefault(); }}
      onSubmitCapture={event => { if (composing.current) { event.preventDefault(); event.stopPropagation(); } }}>
      <header className="studio-sheet-heading"><h2 id={titleId}>{title}</h2><button type="button" className="secondary" disabled={locked} onClick={onClose}>{t("关闭 Close")}</button></header>
      {children}
    </div>
  </div>;
}
