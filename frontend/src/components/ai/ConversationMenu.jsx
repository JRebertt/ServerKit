import { useEffect, useRef, useState } from 'react';
import { History, Plus, Trash2 } from 'lucide-react';
import { useServerkitAI } from '../../contexts/AIContext';
import { useTranslation } from 'react-i18next';

const ConversationMenu = () => {
    const { t } = useTranslation();
    const {
        conversations, activeId, newConversation, switchConversation, deleteConversation, loadConversations,
    } = useServerkitAI();
    const [open, setOpen] = useState(false);
    const wrapRef = useRef(null);

    useEffect(() => {
        if (!open) return undefined;
        loadConversations();
        const onClick = (e) => {
            if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
        };
        document.addEventListener('mousedown', onClick);
        return () => document.removeEventListener('mousedown', onClick);
    }, [open, loadConversations]);

    return (
        <div className="sk-ai-convo" ref={wrapRef}>
            <button
                type="button"
                className="sk-ai-iconbtn"
                aria-label={t('app.conversationMenu.conversations', 'Conversations')}
                aria-expanded={open}
                onClick={() => setOpen((v) => !v)}
            >
                <History size={16} />
            </button>
            {open ? (
                <div className="sk-ai-convo__menu" role="menu">
                    <button
                        type="button"
                        className="sk-ai-convo__new"
                        onClick={() => { newConversation(); setOpen(false); }}
                    >
                        <Plus size={14} /> {t('app.conversationMenu.newChat', 'New chat')}
                    </button>
                    <div className="sk-ai-convo__list">
                        {conversations.length === 0 ? (
                            <div className="sk-ai-convo__empty">{t('app.conversationMenu.noPastConversations', 'No past conversations')}</div>
                        ) : conversations.map((c) => (
                            <div
                                key={c.id}
                                className={`sk-ai-convo__item${c.id === activeId ? ' is-active' : ''}`}
                            >
                                <button
                                    type="button"
                                    className="sk-ai-convo__title"
                                    onClick={() => { switchConversation(c.id); setOpen(false); }}
                                    title={c.title}
                                >
                                    {c.title}
                                </button>
                                <button
                                    type="button"
                                    className="sk-ai-convo__del"
                                    aria-label={t('app.conversationMenu.deleteConversation', 'Delete conversation')}
                                    onClick={() => deleteConversation(c.id)}
                                >
                                    <Trash2 size={13} />
                                </button>
                            </div>
                        ))}
                    </div>
                </div>
            ) : null}
        </div>
    );
};

export default ConversationMenu;
