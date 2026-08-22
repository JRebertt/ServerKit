import { useEffect } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { useServerkitAI } from '../../contexts/AIContext';
import ChatBubble from './ChatBubble';
import ChatDrawer from './ChatDrawer';

// Core assistant overlay. Mounted once in DashboardLayout (owns its own
// z-index — no plugin coexistence hacks). Renders the bubble everywhere and
// the drawer when open.
const AIAssistant = ({ hideLauncher = false }) => {
    const { isAuthenticated } = useAuth();
    const { isOpen, toggle, isStreaming, unread, pageContext } = useServerkitAI();

    // Alt+A toggles the assistant (ignored while typing in a field). Users who
    // find the global shortcut intrusive can disable it by setting
    // localStorage 'sk_ai_shortcut' to 'off'; the bubble's title/aria-label
    // keeps the binding discoverable for everyone else.
    useEffect(() => {
        if (localStorage.getItem('sk_ai_shortcut') === 'off') return undefined;
        const onKeyDown = (e) => {
            if (!e.altKey || (e.key !== 'a' && e.key !== 'A')) return;
            const t = document.activeElement;
            const tag = t?.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || t?.isContentEditable) return;
            e.preventDefault();
            toggle();
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [toggle]);

    if (!isAuthenticated) return null;

    const raised = /^\/servers\/[^/]+/.test(pageContext.route || '');

    return (
        <>
            {!hideLauncher && <ChatBubble open={isOpen} unread={unread} streaming={isStreaming} raised={raised} onToggle={toggle} />}
            {isOpen ? <ChatDrawer /> : null}
        </>
    );
};

export default AIAssistant;
