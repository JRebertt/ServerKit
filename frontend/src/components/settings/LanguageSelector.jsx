import { useTranslation } from 'react-i18next';
import { Languages } from 'lucide-react';
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { useLocale } from '../../contexts/LocaleContext';
import useSettingFocus from '../../hooks/useSettingFocus';

/**
 * Panel language (plan 79 B3).
 *
 * Lives next to the theme picker because it is the same shape of choice: a
 * per-user preference that changes how every screen reads. It also persists
 * the same way — immediately to localStorage so the sign-in screen honours it
 * before anyone is authenticated, and to the user row so it survives a
 * different browser.
 *
 * Built on ui/select rather than a hand-rolled dropdown, so it inherits the
 * keyboard and focus behaviour of every other select in the panel.
 */
const LanguageSelector = () => {
    const { t } = useTranslation();
    const { language, setLanguage, languages } = useLocale();
    const register = useSettingFocus();

    return (
        <div {...register('appearance-language', 'settings-card')}>
            <h3>
                <Languages size={16} aria-hidden="true" /> {t('settings.language.title', 'Language')}
            </h3>
            <p>{t('settings.language.description', 'The language used across the panel.')}</p>

            <Select value={language} onValueChange={setLanguage}>
                <SelectTrigger
                    className="settings-select"
                    aria-label={t('settings.language.title', 'Language')}
                >
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    {languages.map((entry) => (
                        <SelectItem key={entry.code} value={entry.code}>
                            {entry.nativeName}
                            {entry.name !== entry.nativeName && ` — ${entry.name}`}
                            {/* Machine-translated locales say so rather than
                                letting a rough translation read as finished. */}
                            {entry.status === 'provisional'
                                && ` (${t('settings.language.provisional', 'in progress')})`}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </div>
    );
};

export default LanguageSelector;
