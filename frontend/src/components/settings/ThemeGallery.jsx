import { useState } from 'react';
import { Check, Star, Trash2 } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext';
import { useAuth } from '../../contexts/AuthContext';
import { useToast } from '../../contexts/ToastContext';
import { DEFAULT_THEME_SLUG } from '../../data/bundledThemes';
import api from '../../services/api';
import { useTranslation } from 'react-i18next';

// Theme Gallery — cards for every selectable skin (bundled seeds + installed).
// Apply is instant (tokens are already local); hovering previews live and
// leaving restores the selected skin. Admins can additionally set the panel
// default (what login/setup and new users get) and remove installed themes.
const ThemeGallery = () => {
    const { t } = useTranslation();
    const {
        availableThemes, skin, setSkin, previewSkin, clearPreview,
        panelDefaultSlug, refreshInstalledThemes, refreshPanelDefault,
    } = useTheme();
    const { user } = useAuth();
    const toast = useToast();
    const isAdmin = user?.role === 'admin';
    const [busy, setBusy] = useState(null);

    const setDefault = async (slug) => {
        setBusy(slug);
        try {
            await api.setDefaultTheme(slug);
            await refreshPanelDefault();
            toast.success(t('app.themeGallery.panelDefaultThemeUpdated', 'Panel default theme updated'));
        } catch (e) {
            toast.error(e?.message || t('app.themeGallery.couldNotSetTheDefaultTheme', 'Could not set the default theme'));
        } finally {
            setBusy(null);
        }
    };

    const removeTheme = async (slug) => {
        setBusy(slug);
        try {
            await api.deleteTheme(slug);
            await Promise.all([refreshInstalledThemes(), refreshPanelDefault()]);
            toast.success(t('app.themeGallery.themeRemoved', 'Theme removed'));
        } catch (e) {
            toast.error(e?.message || t('app.themeGallery.couldNotRemoveTheTheme', 'Could not remove the theme'));
        } finally {
            setBusy(null);
        }
    };

    const select = (slug) => setSkin(slug);

    return (
        <div className="theme-gallery">
            {availableThemes.map((t) => {
                const isDefault = t.slug === DEFAULT_THEME_SLUG;
                const active = skin === t.slug;
                const isPanelDefault = t.slug === panelDefaultSlug;
                const removable = t.installed && !t.builtin && !isDefault;
                const swatches = Array.isArray(t.preview) ? t.preview.slice(0, 4) : [];
                return (
                    <div
                        key={t.slug}
                        role="button"
                        tabIndex={0}
                        className={`theme-card${active ? ' theme-card--active' : ''}`}
                        onClick={() => select(t.slug)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(t.slug); }
                        }}
                        onMouseEnter={() => previewSkin(isDefault ? null : t)}
                        onMouseLeave={clearPreview}
                        onFocus={() => previewSkin(isDefault ? null : t)}
                        onBlur={clearPreview}
                    >
                        <div className="theme-card__swatches">
                            {swatches.map((color, i) => (
                                <span
                                    key={i}
                                    className="theme-card__swatch"
                                    style={{ background: color }}
                                />
                            ))}
                        </div>
                        <div className="theme-card__meta">
                            <span className="theme-card__name">{t.name || t.slug}</span>
                            {t.base && <span className="theme-card__base">{t.base}</span>}
                        </div>
                        {t.description && (
                            <p className="theme-card__desc">{t.description}</p>
                        )}
                        <div className="theme-card__footer">
                            {active && (
                                <span className="theme-card__applied">
                                    <Check size={13} /> {t('app.themeGallery.applied', 'Applied')}
                                </span>
                            )}
                            {isPanelDefault && (
                                <span className="theme-card__default" title={t('app.themeGallery.defaultForTheWholePanel', 'Default for the whole panel')}>
                                    <Star size={12} /> {t('app.themeGallery.panelDefault', 'Panel default')}
                                </span>
                            )}
                        </div>
                        {isAdmin && (
                            <div className="theme-card__admin">
                                {!isPanelDefault && (
                                    <button
                                        type="button"
                                        className="theme-card__admin-btn"
                                        disabled={busy === t.slug}
                                        onClick={(e) => { e.stopPropagation(); setDefault(t.slug); }}
                                    >
                                        <Star size={12} /> {t('app.themeGallery.setDefault', 'Set default')}
                                    </button>
                                )}
                                {removable && (
                                    <button
                                        type="button"
                                        className="theme-card__admin-btn theme-card__admin-btn--danger"
                                        disabled={busy === t.slug}
                                        onClick={(e) => { e.stopPropagation(); removeTheme(t.slug); }}
                                    >
                                        <Trash2 size={12} /> {t('app.themeGallery.remove', 'Remove')}
                                    </button>
                                )}
                            </div>
                        )}
                    </div>
                );
            })}
        </div>
    );
};

export default ThemeGallery;
