import { useRef } from 'react';
import { StudioSheet } from './StudioSheet';
import { t } from './i18n';
import type { MaterialSuggestionMode } from './types';

type MaterialScope = 'selection' | 'project';

export function MaterialSuggestionDrawer({ revision, scope, scopeName, assignedCount, preference, replaceExisting,
  connected, allowPalette, busy, locked, error, onScopeChange, onPreferenceChange, onReplaceChange,
  onSubmit, onShowExisting, onConnect, onLibrary, onClose }: {
  revision: number; scope: MaterialScope; scopeName: string; assignedCount: number; preference: string;
  replaceExisting: boolean; connected: boolean; allowPalette: boolean; busy: boolean; locked: boolean; error: string;
  onScopeChange: (scope: MaterialScope) => void; onPreferenceChange: (preference: string) => void;
  onReplaceChange: (replace: boolean) => void; onSubmit: (mode: MaterialSuggestionMode) => void;
  onShowExisting: () => void; onConnect: () => void; onLibrary: () => void; onClose: () => void;
}) {
  const moreOptions = useRef<HTMLDetailsElement>(null);
  const replaceOption = useRef<HTMLInputElement>(null);
  const allAssigned = assignedCount > 0 && !replaceExisting;
  const hasPreference = !!preference.trim();
  const unavailable = locked || allAssigned;
  const primaryDisabled = unavailable || !connected && hasPreference;
  const scopeLabel = scope === 'project' ? t('Whole project', '整个项目') : t(scopeName);

  return <StudioSheet title={t('AI material suggestions', 'AI材料建议')} titleId="material-suggestions-title" onClose={onClose} locked={busy}>
    <form className="sheet-body material-suggestion-form" onSubmit={event => {
      event.preventDefault();
      if (!primaryDisabled) onSubmit(connected ? 'api' : 'source');
    }}>
      <p className="material-suggestion-scope"><strong>{scopeLabel}</strong>
        <span>{replaceExisting ? t('Allow replacing assignments', '允许替换现有分配') : t('Fill unassigned materials', '为未分配的构件建议材料')} · R{revision}</span>
      </p>
      <p>{connected
        ? t('Studio uses your drawings and material library to suggest finishes and stock. Review the suggestions before applying.', 'Studio 根据图纸和材料库建议饰面与库存板材。应用前请审阅建议。')
        : t('AI is disconnected. Studio can match PDF finishes to your library locally.', 'AI 尚未连接。Studio 可以在本地将 PDF 饰面与材料库匹配。')}</p>
      {(connected || hasPreference) && <label className="input-label">
        {t('Describe the materials you want (optional)', '描述你希望使用的材料（可选）')}
        <textarea aria-label={t('Describe the materials you want', '描述你希望使用的材料')} rows={3} maxLength={4000}
          value={preference} disabled={busy} onChange={event => onPreferenceChange(event.target.value)}
          placeholder={t('For example, a warm oak finish on the island.', '例如，岛台采用暖色橡木饰面。')} />
      </label>}
      {hasPreference && !connected && <p className="hint">{t('Connect AI to use your preferences, or clear them to match finishes locally.', '连接 AI 以使用偏好，或清空偏好以在本地匹配饰面。')}</p>}
      {allAssigned && <div className="material-existing-choice" role="status">
        <strong>{t('All eligible parts already have materials', '所有可分配构件均已有材料')}</strong>
        <p>{t(`${assignedCount} parts have saved assignments. View them or enable replacement in More options.`, `${assignedCount} 个构件已有材料分配。可查看已有材质，或在更多选项中启用替换。`)}</p>
        <div className="material-suggestion-alternatives">
          <button type="button" className="secondary" disabled={busy} onClick={onShowExisting}>{t('Show existing materials', '显示现有材质')}</button>
          <button type="button" className="subtle" disabled={busy} onClick={() => {
            if (moreOptions.current) moreOptions.current.open = true;
            replaceOption.current?.focus();
          }}>{t('Review replacement options', '查看替换选项')}</button>
        </div>
      </div>}
      <details ref={moreOptions} className="material-suggestion-options">
        <summary>{t('More options', '更多选项')}</summary>
        <label className="input-label">{t('Apply suggestions to', '建议应用范围')}
          <select aria-label={t('Material suggestion scope', '材料建议范围')} value={scope} disabled={busy}
            onChange={event => onScopeChange(event.target.value as MaterialScope)}>
            <option value="project">{t('Whole project', '整个项目')}</option>
            <option value="selection">{t('Selected object and its panels', '所选构件及其板件')}</option>
          </select>
        </label>
        <label className="sheet-checkbox"><input ref={replaceOption} type="checkbox" checked={replaceExisting} disabled={busy}
          onChange={event => onReplaceChange(event.target.checked)} />
          {t('Replace existing material assignments', '替换已有材料分配')}
        </label>
        {hasPreference && connected && <p className="hint">{t('Clear your preferences to use the local options.', '清空偏好后即可使用本地选项。')}</p>}
        <div className="material-suggestion-alternatives">
          {connected && <button type="button" className="secondary" disabled={unavailable || hasPreference}
            onClick={() => onSubmit('source')}>{t('Match source finishes', '匹配原图饰面')}</button>}
          {allowPalette && <button type="button" className="secondary" disabled={unavailable || hasPreference}
            onClick={() => onSubmit('prepared')}>{t('Use project palette', '使用项目材料方案')}</button>}
          <button type="button" className="subtle" disabled={busy} onClick={onLibrary}>{t('Open material library', '打开材料库')}</button>
        </div>
      </details>
      {error && <p className="field-error" role="alert">{t(error)}</p>}
      <div className="sheet-actions">
        {!connected && <button type="button" className="secondary" disabled={busy} onClick={onConnect}>{t('Connect AI', '连接 AI')}</button>}
        <button type="submit" className="primary" data-autofocus={primaryDisabled ? undefined : true} disabled={primaryDisabled}>
          {connected ? t('Suggest materials', '推荐材料') : t('Match source finishes', '匹配原图饰面')}
        </button>
      </div>
    </form>
  </StudioSheet>;
}
