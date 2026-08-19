import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { serviceStatusVariant, serviceStatusDotClass, statusLabel } from '@/components/ds/status';

// One vocabulary (plan 77 D3): variant, dot color and label all derive from
// ds/status.js — service-scoped, so "running" stays the healthy green.

export default function StatusBadge({ status, label, className = '' }) {
  const variant = serviceStatusVariant(status);
  const dotColor = serviceStatusDotClass(status);
  const displayLabel = label || (status ? statusLabel(status) : status);

  return (
    <Badge variant={variant} className={cn('status-badge-token', className)}>
      <span className={cn('size-1.5 rounded-full shrink-0', dotColor)} />
      {displayLabel}
    </Badge>
  );
}
