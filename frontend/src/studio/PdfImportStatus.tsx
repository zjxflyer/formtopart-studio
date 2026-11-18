import { t } from './i18n';
import './pdf-import.css';

type ImportFile = { filename: string; projectId?: string };
export type PdfImportState = ImportFile & (
  | { phase: 'preparing' | 'importing' | 'opening' }
  | { phase: 'ready'; pages?: number; alreadyPresent: boolean }
  | { phase: 'failed' | 'openingFailed'; message: string }
);

export function pdfImportInProgress(state: PdfImportState | null) {
  return state?.phase === 'preparing' || state?.phase === 'importing' || state?.phase === 'opening';
}

export function PdfImportStatus({ state, onDismiss }: { state: PdfImportState; onDismiss: () => void }) {
  const active = pdfImportInProgress(state);
  const failed = state.phase === 'failed' || state.phase === 'openingFailed';
  let title: string;
  let detail: string;
  switch (state.phase) {
    case 'preparing':
      title = t('Preparing project…', '正在准备项目…');
      detail = t('Creating a local project for this PDF.', '正在为此 PDF 创建本地项目。');
      break;
    case 'importing':
      title = t('Importing PDF…', '正在导入 PDF…');
      detail = t('Reading the file and preparing page previews.', '正在读取文件并生成页面预览。');
      break;
    case 'opening':
      title = t('Opening PDF previews…', '正在打开 PDF 预览…');
      detail = t('Loading the imported pages in your project.', '正在项目中加载已导入的页面。');
      break;
    case 'ready':
      title = state.alreadyPresent ? t('PDF already in this project', '此 PDF 已在项目中') : t('PDF imported', 'PDF 已导入');
      detail = state.pages == null ? t('Source pages ready to review', '原图页面已可查看')
        : state.pages === 1 ? t('1 page ready to review', '1 页原图已可查看')
        : t(`${state.pages} pages ready to review`, `${state.pages} 页原图已可查看`);
      break;
    case 'failed':
      title = t('PDF import failed', 'PDF 导入失败');
      detail = t(state.message);
      break;
    case 'openingFailed':
      title = t('PDF imported. Previews could not open.', 'PDF 已导入，预览暂时无法打开。');
      detail = t('Refresh Studio to open the imported pages.', '刷新 Studio 后可打开已导入的页面。') + ' ' + t(state.message);
      break;
  }
  return <div className={`pdf-import-status${failed ? ' is-error' : ''}`}>
    <div className="pdf-import-copy" role={failed ? 'alert' : 'status'}>
      <div className="pdf-import-title"><strong>{title}</strong><span title={state.filename}>{state.filename}</span></div>
      <p>{detail}</p>
    </div>
    {active ? <div className="pdf-import-progress" role="progressbar" aria-label={t('PDF import progress', 'PDF 导入进度')}>
      <span />
    </div> : <button type="button" className="subtle pdf-import-dismiss" onClick={onDismiss}
      aria-label={t('Dismiss PDF import status', '关闭 PDF 导入提示')}>{t('Dismiss', '关闭')}</button>}
  </div>;
}
