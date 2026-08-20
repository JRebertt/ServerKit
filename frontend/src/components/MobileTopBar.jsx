import { Menu, X } from 'lucide-react';
import { t } from '../i18n';
import { useTheme } from '../contexts/ThemeContext';
import ServerKitLogo from './ServerKitLogo';
import NotificationBell from './NotificationBell';
import QuickCreate from './QuickCreate';

// Fixed header shown only on narrow viewports (< 768px). Houses the
// hamburger toggle that opens the sidebar as an off-canvas drawer, since
// the persistent sidebar is hidden at this width. Hidden on desktop via CSS.
const MobileTopBar = ({ navOpen, onToggle }) => {
    const { whiteLabel } = useTheme();
    const branded = whiteLabel?.enabled;
    const brandName = branded ? (whiteLabel.brandName || 'Brand') : 'ServerKit';
    const showCustomLogo = branded && whiteLabel.logoData && whiteLabel.mode !== 'text_only';

    return (
        <header className="mobile-topbar">
            <button
                type="button"
                className="mobile-topbar__toggle"
                aria-label={navOpen
                    ? t('nav.closeMenu', 'Close navigation menu')
                    : t('nav.openMenu', 'Open navigation menu')}
                aria-expanded={navOpen}
                aria-controls="primary-navigation"
                onClick={onToggle}
            >
                {navOpen ? <X size={22} aria-hidden="true" /> : <Menu size={22} aria-hidden="true" />}
            </button>
            <div className="mobile-topbar__brand">
                {!branded && (
                    <span className="mobile-topbar__logo">
                        <ServerKitLogo width={26} height={26} />
                    </span>
                )}
                {showCustomLogo && (
                    <span className="mobile-topbar__logo">
                        <img src={whiteLabel.logoData} alt="" />
                    </span>
                )}
                <span className="mobile-topbar__name">{brandName}</span>
            </div>
            <div className="mobile-topbar__actions">
                <QuickCreate />
                <NotificationBell />
            </div>
        </header>
    );
};

export default MobileTopBar;
