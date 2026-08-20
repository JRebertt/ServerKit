import { t } from '../i18n/t';
/**
 * Full-screen initial loader shown while auth/setup state is resolved.
 *
 * A ServerKit-branded tile holding the server glyph whose status LEDs blink like
 * a machine booting, plus a slim indeterminate progress bar. No spinner — the
 * server "powering on" is the loading metaphor. Matches the sidebar brand mark
 * and the favicon so first paint feels of-a-piece.
 */
export function AppLoader() {
    return (
        <div className="app-loader" role="status" aria-live="polite" aria-label={t('common.state.loadingApp', 'Loading ServerKit')}>
            <div className="app-loader__logo">
                <svg
                    className="app-loader__glyph"
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={2}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                >
                    <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
                    <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
                    <line className="app-loader__led app-loader__led--1" x1="6" y1="6" x2="6.01" y2="6" />
                    <line className="app-loader__led app-loader__led--2" x1="6" y1="18" x2="6.01" y2="18" />
                </svg>
            </div>
            <div className="app-loader__bar" aria-hidden="true">
                <span className="app-loader__bar-fill" />
            </div>
            <span className="app-loader__label">{t('common.state.loadingApp', 'Loading ServerKit')}</span>
        </div>
    );
}

export default AppLoader;
