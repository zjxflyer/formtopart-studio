import { useEffect, useRef, useState, type FormEvent } from 'react';
import { studioAPI } from './api';
import { StudioSheet } from './StudioSheet';
import { t } from './i18n';
import { modelDisplayName } from './modelLabel';
import type { KeySettings as Settings } from './types';

export function KeySettings({ onClose, onSaved }: { onClose: () => void; onSaved: (settings: Settings) => void }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [model, setModel] = useState('gpt-6.1-terra');
  const [key, setKey] = useState(''); const [visible, setVisible] = useState(false);
  const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false);
  const [error, setError] = useState(''); const [saved, setSaved] = useState(false);
  const mutex = useRef(false);
  useEffect(() => {
    let cancelled = false;
    void studioAPI.keySettings().then(value => { if (!cancelled) { setSettings(value); setModel(value.model); } })
      .catch(reason => { if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);
  async function save(event: FormEvent) {
    event.preventDefault(); if (mutex.current || loading || !settings) return;
    mutex.current = true; setBusy(true); setError(''); setSaved(false);
    try {
      const next = await studioAPI.saveKeySettings(model, key);
      setKey(''); setVisible(false); setSettings(next); setSaved(true); onSaved(next);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { mutex.current = false; setBusy(false); }
  }
  return <StudioSheet title={t('Assistant settings', '设计助手设置')} titleId="assistant-settings-title" onClose={onClose} locked={busy}>
    <form className="sheet-body key-settings-form" onSubmit={event => void save(event)}>
      {loading ? <p role="status">{t('Loading settings…', '正在读取设置…')}</p> : <>
        <div className={`key-saved-state ${settings?.key_available ? 'configured' : ''}`}><span aria-hidden="true">{settings?.key_available ? '✓' : '○'}</span><div><strong>{settings?.key_available ? t('Saved key configured', '已配置保存的密钥') : t('Connect your OpenAI account', '连接你的OpenAI账户')}</strong><p>{settings?.key_available ? t('Your existing key is ready to use. Leave the field empty to keep it.', '已有密钥可直接使用，留空即可保留。') : t('Enter a key to enable the design assistant.', '输入密钥后可启用设计助手。')}</p></div></div>
        <fieldset disabled={busy || !settings}><label className="input-label">{t('OpenAI API key', 'OpenAI API密钥')}<input data-autofocus type={visible ? 'text' : 'password'} value={key} maxLength={4096} autoComplete="off" spellCheck={false} aria-label={t('OpenAI API key', 'OpenAI API密钥')} placeholder={settings?.key_available ? t('Leave empty to keep the saved key', '留空以保留已保存密钥') : 'sk-…'} onChange={event => { setKey(event.target.value); setSaved(false); }} /></label>
        <label className="sheet-checkbox"><input type="checkbox" checked={visible} onChange={event => setVisible(event.target.checked)} />{t('Show the key I am typing', '显示正在输入的密钥')}</label>
        <label className="input-label">{t('Model', '模型')}<select aria-label={t('Assistant model', '助手模型')} value={model} onChange={event => { setModel(event.target.value); setSaved(false); }}>{(settings?.models || ['gpt-6.1-terra', 'gpt-6.1-sol']).map(value => <option value={value} key={value}>{modelDisplayName(value)}</option>)}</select></label><p className="hint">{t('Reasoning: High', '推理强度：高')}</p>
        <p className="hint">{t('The key is protected by your Windows account and saved on this computer.', '密钥由你的Windows账户加密保护，并保存在本机。')}</p></fieldset>
      </>}
      {error && <p className="field-error" role="alert">{t(error)}</p>}
      {saved && <p className="settings-saved" role="status">{t('Settings saved.', '设置已保存。')}</p>}
      <div className="sheet-actions"><button className="secondary" type="button" disabled={busy} onClick={onClose}>{t('Close', '关闭')}</button><button className="primary" type="submit" disabled={busy || loading || !settings}>{busy ? t('Saving…', '正在保存…') : t('Save settings', '保存设置')}</button></div>
    </form>
  </StudioSheet>;
}
