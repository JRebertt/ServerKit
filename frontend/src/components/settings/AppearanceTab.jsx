import { useRef, useState } from 'react';
import { useTheme } from '../../contexts/ThemeContext';
import { useAuth } from '../../contexts/AuthContext';
import { useToast } from '../../contexts/ToastContext';
import { Link } from 'react-router-dom';
import { RotateCcw, Upload, Store, Sparkles, LayoutGrid } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import useSettingFocus from '../../hooks/useSettingFocus';
import ThemeGallery from './ThemeGallery';
import ThemeBrowseModal from './ThemeBrowseModal';
import ThemeStudioModal from './ThemeStudioModal';
import api from '../../services/api';

const ACCENT_PRESETS = [
    { label: 'Indigo', color: '#6366f1' },
    { label: 'Ocean', color: '#0ea5e9' },
    { label: 'Forest', color: '#10b981' },
    { label: 'Sunset', color: '#f97316' },
    { label: 'Rose', color: '#f43f5e' },
    { label: 'Violet', color: '#8b5cf6' },
    { label: 'Amber', color: '#f59e0b' },
    { label: 'Cyan', color: '#06b6d4' },
];

const AppearanceTab = () => {
    const {
        theme, setTheme, accentColor, setAccentColor, hasCustomAccent, resetAccentColor,
        refreshInstalledThemes, setSkin,
    } = useTheme();
    const { user } = useAuth();
    const toast = useToast();
    const register = useSettingFocus();
    const fileInputRef = useRef(null);
    const [browseOpen, setBrowseOpen] = useState(false);
    const [studioOpen, setStudioOpen] = useState(false);
    const isAdmin = user?.role === 'admin';

    const onImportFile = async (e) => {
        const file = e.target.files?.[0];
        e.target.value = '';               // allow re-selecting the same file
        if (!file) return;
        try {
            const imported = await api.importThemeFile(file);
            await refreshInstalledThemes();
            if (imported?.slug) setSkin(imported.slug);
            toast.success(`Imported theme "${imported?.name || imported?.slug}"`);
        } catch (err) {
            toast.error(err?.message || 'Could not import that theme.json');
        }
    };

    return (
        <div className="settings-section">
            <div className="section-header">
                <h2>Appearance</h2>
                <p>Customize the look and feel of your dashboard</p>
            </div>

            <div {...register('appearance-theme', 'settings-card')}>
                <h3>Theme</h3>
                <p>Select your preferred color scheme</p>
                <div className="theme-options">
                    <button type="button"
                        className={`theme-option ${theme === 'dark' ? 'active' : ''}`}
                        onClick={() => setTheme('dark')}
                    >
                        <div className="theme-preview dark">
                            <div className="preview-sidebar"></div>
                            <div className="preview-content">
                                <div className="preview-card"></div>
                                <div className="preview-card"></div>
                            </div>
                        </div>
                        <span>Dark</span>
                    </button>
                    <button type="button"
                        className={`theme-option ${theme === 'light' ? 'active' : ''}`}
                        onClick={() => setTheme('light')}
                    >
                        <div className="theme-preview light">
                            <div className="preview-sidebar"></div>
                            <div className="preview-content">
                                <div className="preview-card"></div>
                                <div className="preview-card"></div>
                            </div>
                        </div>
                        <span>Light</span>
                    </button>
                    <button type="button"
                        className={`theme-option ${theme === 'system' ? 'active' : ''}`}
                        onClick={() => setTheme('system')}
                    >
                        <div className="theme-preview system">
                            <div className="preview-sidebar"></div>
                            <div className="preview-content">
                                <div className="preview-card"></div>
                                <div className="preview-card"></div>
                            </div>
                        </div>
                        <span>System</span>
                    </button>
                </div>
            </div>

            <div {...register('appearance-theme-gallery', 'settings-card')}>
                <div className="theme-gallery-header">
                    <div>
                        <h3>Theme</h3>
                        <p>Pick a color theme. Applies instantly and stays your personal choice; the dark/light toggle above still works on top of it.</p>
                    </div>
                    <div className="theme-gallery-actions">
                        <Button variant="outline" size="sm" onClick={() => setStudioOpen(true)}>
                            <Sparkles size={14} />
                            Create theme
                        </Button>
                        {isAdmin && (
                            <>
                                <input
                                    ref={fileInputRef}
                                    type="file"
                                    accept="application/json,.json"
                                    style={{ display: 'none' }}
                                    onChange={onImportFile}
                                />
                                <Button variant="outline" size="sm" onClick={() => setBrowseOpen(true)}>
                                    <Store size={14} />
                                    Browse themes
                                </Button>
                                <Button variant="outline" size="sm" onClick={() => fileInputRef.current?.click()}>
                                    <Upload size={14} />
                                    Import theme.json
                                </Button>
                            </>
                        )}
                    </div>
                </div>
                <ThemeGallery />
                <ThemeBrowseModal open={browseOpen} onOpenChange={setBrowseOpen} />
                <ThemeStudioModal open={studioOpen} onOpenChange={setStudioOpen} />
            </div>

            <div {...register('appearance-accent-color', 'settings-card')}>
                <h3>Accent Color</h3>
                <p>Choose the primary accent color used across the interface</p>
                <div className="accent-presets">
                    {ACCENT_PRESETS.map(({ label, color }) => (
                        <button type="button"
                            key={color}
                            className={`accent-preset${accentColor === color ? ' active' : ''}`}
                            onClick={() => setAccentColor(color)}
                        >
                            <span className="accent-swatch" style={{ background: color }} />
                            <span className="accent-label">{label}</span>
                        </button>
                    ))}
                </div>
                <div className="accent-custom">
                    <label className="accent-custom-label">Custom color</label>
                    <div className="accent-custom-row">
                        <input
                            type="color"
                            className="accent-custom-input"
                            value={accentColor}
                            onChange={(e) => setAccentColor(e.target.value)}
                        />
                        <span className="accent-custom-hex">{accentColor.toUpperCase()}</span>
                        {hasCustomAccent && (
                            <button
                                type="button"
                                className="accent-custom-reset"
                                onClick={resetAccentColor}
                                title="Use the theme's accent"
                            >
                                <RotateCcw size={13} /> Use theme accent
                            </button>
                        )}
                    </div>
                </div>
            </div>

            <div {...register('appearance-widgets', 'settings-card')}>
                <h3>Dashboard Widgets</h3>
                <p>
                    Widgets are arranged on the dashboard itself now — add, move, resize and
                    configure them in place, across as many boards as you need.
                </p>
                <Button variant="outline" size="sm" asChild>
                    <Link to="/">
                        <LayoutGrid size={14} />
                        Edit dashboards
                    </Link>
                </Button>
            </div>

        </div>
    );
};

export default AppearanceTab;
