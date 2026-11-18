const MODEL_LABELS: Record<string, string> = {
  'gpt-6.1-terra': 'Terra',
  'gpt-6.1-sol': 'Sol',
  'gpt-6-astra': 'Astra',
};

export function modelDisplayName(model: string): string {
  return MODEL_LABELS[model] || model || 'AI';
}
