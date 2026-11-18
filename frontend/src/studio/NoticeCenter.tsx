import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react';
import { t, useLanguage } from './i18n';
import { StudioSheet } from './StudioSheet';
import './notices.css';

export type StudioNotice = {
  id: string;
  title: string;
  tone?: 'info' | 'warning' | 'error' | 'success';
  messages?: string[];
  content?: ReactNode;
  onDismiss?: () => void;
};

type Props = { notices: StudioNotice[]; contextKey: string; requestOpen?: number };

/** Read-only project notices. Opening or closing the sheet never starts work. */
export function NoticeCenter({ notices, contextKey, requestOpen = 0 }: Props) {
  const language = useLanguage();
  const [open, setOpen] = useState(false);
  const priorContext = useRef(contextKey);
  const priorRequest = useRef(requestOpen);
  const id = useId();
  const groups = useMemo(() => notices.map(notice => ({
    ...notice,
    messages: [...new Set((notice.messages || []).map(message => t(message).trim()).filter(Boolean))],
  })), [notices, language]);
  // A content-only or title-only notice still represents one notice. Detailed
  // components do not inflate the badge with their internal DOM text.
  const count = groups.reduce((total, group) => total + Math.max(1, group.messages.length), 0);
  const tone = groups.some(group => group.tone === 'error') ? 'error'
    : groups.some(group => group.tone === 'warning') ? 'warning' : count ? 'info' : 'empty';
  const buttonName = t(`Notices (${count})`, `通知（${count}）`);

  useEffect(() => {
    const contextChanged = priorContext.current !== contextKey;
    const requested = priorRequest.current !== requestOpen && requestOpen > 0;
    priorContext.current = contextKey;
    priorRequest.current = requestOpen;
    if (contextChanged) setOpen(false);
    else if (requested) setOpen(true);
  }, [contextKey, requestOpen]);

  return <>
    <button type="button" className={`notice-center-trigger ${tone}`} aria-label={buttonName}
      aria-haspopup="dialog" aria-expanded={open} aria-controls={`${id}-list`}
      title={t('View notices and review notes', '查看通知与审阅备注')} onClick={() => setOpen(true)}>
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9ZM10 21h4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
      <span>{t('Notices', '通知')}</span><span className="notice-count" aria-hidden="true">{count}</span>
    </button>
    {open && <StudioSheet title={t('Notices', '通知')} titleId={`${id}-title`} onClose={() => setOpen(false)}>
      <div id={`${id}-list`} className="sheet-body notice-center-body">
        {!groups.length ? <p className="notice-center-empty">{t('No notices for this project.', '此项目暂无通知。')}</p>
          : <div className="notice-center-list">{groups.map(group => <section key={group.id}
            className={`notice-center-item ${group.tone || 'info'}`} aria-labelledby={`${id}-${group.id}-title`}>
            <div className="notice-center-item-heading"><h3 id={`${id}-${group.id}-title`}>{t(group.title)}</h3>
              <span className="notice-tone">{group.tone === 'error' ? t('Action needed', '需要处理')
                : group.tone === 'warning' ? t('Review', '请核对')
                : group.tone === 'success' ? t('Complete', '已完成') : t('Information', '信息')}</span>
              {group.onDismiss && <button type="button" className="subtle" aria-label={t(`Dismiss ${t(group.title)}`, `关闭${t(group.title)}`)}
                onClick={group.onDismiss}>{t('Dismiss', '关闭')}</button>}
            </div>
            {!!group.messages.length && <ul>{group.messages.map(message => <li key={message}>{message}</li>)}</ul>}
            {group.content != null && <div className="notice-center-content">{group.content}</div>}
          </section>)}</div>}
      </div>
    </StudioSheet>}
  </>;
}
