import { AlertTriangle, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { t } from '@/i18n/t';

/**
 * Consistent error state for pages and panels. Shows an icon, title, message,
 * and optional retry action.
 *
 *   <ErrorState
 *     title="Failed to load servers"
 *     message="The backend returned an error. Please try again."
 *     onRetry={loadData}
 *   />
 */
export function ErrorState({ title = 'Something went wrong', message, onRetry, className = '' }) {
    return (
        <div className={`sk-error-state ${className}`.trim()}>
            <div className="sk-error-state__icon">
                <AlertTriangle size={32} />
            </div>
            <h3 className="sk-error-state__title">{title}</h3>
            {message && <p className="sk-error-state__message">{message}</p>}
            {onRetry && (
                <Button variant="outline" size="sm" onClick={onRetry}>
                    <RefreshCw size={14} /> {t('common.actions.tryAgain', 'Try again')}
                </Button>
            )}
        </div>
    );
}

export default ErrorState;
