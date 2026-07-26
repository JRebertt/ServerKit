import { Inbox } from 'lucide-react';
import { PageSkeleton } from './PageSkeleton';

/**
 * `loadingVariant` names the shape of the page that is loading — see
 * PageSkeleton for the archetypes (table, feed, cards, detail, console, form,
 * chart, tree, split). It defaults to the generic `panel`, which is a safe
 * fallback but predicts nothing: prefer naming the real shape, so the skeleton
 * resolves into the content instead of being replaced by it.
 */
export default function EmptyState({
    icon: Icon = Inbox,
    title = 'No items found',
    description = '',
    action = null,
    size = 'default',
    loading = false,
    loadingVariant = 'panel',
    loadingRows,
}) {
    if (loading) {
        return (
            <div
                className={`empty-state empty-state--${size} empty-state--loading`}
                role="status"
                aria-busy="true"
                aria-label={title || 'Loading'}
            >
                <PageSkeleton variant={loadingVariant} rows={loadingRows} />
            </div>
        );
    }

    return (
        <div className={`empty-state empty-state--${size}`}>
            <div className="empty-state__icon">
                <Icon size={size === 'lg' ? 64 : 48} />
            </div>
            <h3 className="empty-state__title">{title}</h3>
            {description && (
                <p className="empty-state__description">{description}</p>
            )}
            {action && (
                <div className="empty-state__action">{action}</div>
            )}
        </div>
    );
}
