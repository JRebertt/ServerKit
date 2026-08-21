import { useNavigate } from 'react-router-dom';
import { Settings, X } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import { useServerkitAI } from '../../contexts/AIContext';
import ModeToggle from './ModeToggle';
import ConversationMenu from './ConversationMenu';
import { useTranslation } from 'react-i18next';

const DrawerHeader = () => {
    const { t } = useTranslation();
    const { close } = useServerkitAI();
    const { isAdmin } = useAuth();
    const navigate = useNavigate();

    return (
        <header className="sk-ai-header">
            <div className="sk-ai-header__title">
                <span className="sk-ai-header__name">{t('app.drawerHeader.serverkitAi', 'ServerKit AI')}</span>
                <span className="sk-ai-header__by">{t('app.drawerHeader.poweredByPrompture', 'powered by Prompture')}</span>
            </div>
            <div className="sk-ai-header__actions">
                <ModeToggle />
                <ConversationMenu />
                {isAdmin ? (
                    <button
                        type="button"
                        className="sk-ai-iconbtn"
                        aria-label={t('app.drawerHeader.aiSettings', 'AI settings')}
                        onClick={() => { close(); navigate('/settings/ai'); }}
                    >
                        <Settings size={16} />
                    </button>
                ) : null}
                <button type="button" className="sk-ai-iconbtn" aria-label={t('app.drawerHeader.closeAssistant', 'Close assistant')} onClick={close}>
                    <X size={16} />
                </button>
            </div>
        </header>
    );
};

export default DrawerHeader;
