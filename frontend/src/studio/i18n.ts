import { useSyncExternalStore } from 'react';
import catalog from './i18n-catalog.json';

export type Language = 'en' | 'zh';
const KEY = 'vwc-studio-language';
const EVENT = 'vwc-studio-language-changed';

export function getLanguage(): Language {
  try { return localStorage.getItem(KEY) === 'zh' ? 'zh' : 'en'; } catch { return 'en'; }
}
export function setLanguage(language: Language) {
  try { localStorage.setItem(KEY, language); } catch { /* A private window can still switch for this session. */ }
  sessionLanguage = language;
  if (typeof document !== 'undefined') document.documentElement.lang = language === 'en' ? 'en' : 'zh-CN';
  window.dispatchEvent(new Event(EVENT));
}
let sessionLanguage: Language | undefined;
function currentLanguage() { return sessionLanguage ?? getLanguage(); }
function subscribe(listener: () => void) {
  const storage = (event: StorageEvent) => { if (event.key === KEY) { sessionLanguage = undefined; listener(); } };
  window.addEventListener(EVENT, listener); window.addEventListener('storage', storage);
  return () => { window.removeEventListener(EVENT, listener); window.removeEventListener('storage', storage); };
}
export function useLanguage() {
  return useSyncExternalStore(subscribe, currentLanguage, () => 'en' as Language);
}

/** Translate fixed interface strings and paired server messages; user data is never rewritten. */
export function t(value: string, chinese?: string): string {
  const language = currentLanguage();
  if (chinese !== undefined) return language === 'en' ? value : chinese;
  const pair = (catalog as Record<string, string[]>)[value];
  if (pair) return pair[language === 'en' ? 0 : 1];
  // Server errors use explicit English / Chinese pairs. Preserve arbitrary user content.
  const separator = value.indexOf(' / ');
  if (separator >= 0) {
    const left = value.slice(0, separator), right = value.slice(separator + 3);
    if (/[A-Za-z]/.test(left) && !/[\u3400-\u9fff]/.test(left) && /[\u3400-\u9fff]/.test(right)) return language === 'en' ? left : right;
  }
  return value;
}
