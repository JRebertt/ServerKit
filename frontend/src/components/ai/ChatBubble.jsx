import { MessageSquare, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

// Intercom-style launcher. `raised` lifts it above the serverkit-gui FAB on
// server-detail routes so the two don't overlap.
const ChatBubble = ({ open, unread, streaming, raised, onToggle }) => {
    const { t } = useTranslation();
    return (
        <button
            type="button"
            className={[
                'sk-ai-bubble',
                open ? 'is-open' : '',
                raised ? 'is-raised' : '',
                streaming && !open ? 'is-busy' : '',
            ].filter(Boolean).join(' ')}
            onClick={onToggle}
            aria-label={open ? t('app.chatBubble.closeAssistantAltA', 'Close assistant (Alt+A)') : t('app.chatBubble.openAssistantAltA', 'Open assistant (Alt+A)')}
            title={open ? t('app.chatBubble.closeAssistantAltA2', 'Close assistant (Alt+A)') : t('app.chatBubble.openAssistantAltA2', 'Open assistant (Alt+A)')}
            aria-keyshortcuts="Alt+A"
            aria-expanded={open}
            aria-controls="sk-ai-drawer"
        >
            {open ? <X size={22} /> : <MessageSquare size={22} />}
            {!open && unread > 0 ? <span className="sk-ai-bubble__dot" aria-hidden="true" /> : null}
        </button>
    );
};

export default ChatBubble;
