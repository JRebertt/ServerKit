import EmptyState from './EmptyState';
import { useTranslation } from 'react-i18next';

/**
 * Full-page loader for tab-group pages.
 * Shows a skeleton placeholder inside the standard tab-group inner area.
 */
export function PageLoader({ className = '' }) {
    const { t } = useTranslation();
    return (
        <div className={`sk-tabgroup__inner ${className}`.trim()}>
            <EmptyState loading title={t('app.pageLoader.loading', 'Loading')} />
        </div>
    );
}

export default PageLoader;
