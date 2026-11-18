import type { ReactNode } from 'react';
import { t } from './i18n';

export type BuildAction = {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  reason?: string;
  secondary?: boolean;
  describedBy?: string;
};

function ActionButton({ action }: { action: BuildAction }) {
  return <button type="button" className={action.secondary ? 'secondary' : 'primary'}
    disabled={action.disabled} title={action.reason} aria-describedby={action.describedBy}
    onClick={action.onClick}>{action.label}</button>;
}

export function WorkflowBuildActions({ all, selected, scope, resume }: {
  all?: BuildAction;
  selected?: BuildAction;
  scope?: ReactNode;
  resume?: BuildAction;
}) {
  return <div className="workflow-build-actions" role="group" aria-label={t('Build controls', '构建控制')}>
    {resume && <ActionButton action={resume} />}
    {all && <ActionButton action={all} />}
    {scope}
    {selected && <ActionButton action={selected} />}
  </div>;
}
