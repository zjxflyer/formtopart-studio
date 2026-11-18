import { t } from './i18n';
import './production-guide.css';

export type ProductionAction = {
  title: string;
  description: string;
  label?: string;
  onClick?: () => void;
  disabled?: boolean;
};

export function ProductionGuide({ action }: { action: ProductionAction }) {
  return <section className="production-guide" aria-label={t('Next action', '下一步操作')}>
    <div><strong>{action.title}</strong><p>{action.description}</p></div>
    {action.label && action.onClick && <button type="button" className="primary" disabled={action.disabled}
      onClick={action.onClick}>{action.label}</button>}
  </section>;
}
