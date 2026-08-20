import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell, Check, X } from 'lucide-react';
import { useNotifications } from '../contexts/NotificationsContext';
import { timeAgo } from '../utils/time';

// Severity → dot color, mirroring the email/brand palette.
const SEVERITY_DOT = {
    critical: '#fb6f6f',
    warning: '#f5b945',
    success: '#3ddc97',
    info: '#6d7cff',
    test: '#9aa1b2',
};

export default function NotificationBell() {
    const ctx = useNotifications();
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    const navigate = useNavigate();

    // The provider is only mounted for authenticated users; render nothing otherwise.
    const { items = [], unreadCount = 0, markRead, markAllRead, refresh, dismissNotice } = ctx || {};

    useEffect(() => {
        if (!open) return undefined;
        const onDocClick = (e) => {
            if (ref.current && !ref.current.contains(e.target)) setOpen(false);
        };
        const onEsc = (e) => { if (e.key === 'Escape') setOpen(false); };
        document.addEventListener('mousedown', onDocClick);
        document.addEventListener('keydown', onEsc);
        return () => {
            document.removeEventListener('mousedown', onDocClick);
            document.removeEventListener('keydown', onEsc);
        };
    }, [open]);

    if (!ctx) return null;

    const toggle = () => {
        const next = !open;
        setOpen(next);
        if (next && refresh) refresh();
    };

    const onItemClick = (item) => {
        // System notices route to their fix; bus notifications mark read and
        // then deep-link to their subject when they carry an action_path.
        if (item.kind === 'notice') {
            setOpen(false);
            if (item.action_path) navigate(item.action_path);
            return;
        }
        if (!item.read && markRead) markRead(item.delivery_id);
        if (item.action_path) {
            setOpen(false);
            navigate(item.action_path);
        }
    };

    const badge = unreadCount > 99 ? '99+' : unreadCount;

    return (
        <div className="sk-notif" ref={ref}>
            <button
                type="button"
                className="sk-notif__bell"
                onClick={toggle}
                aria-label={unreadCount ? `Notifications, ${unreadCount} unread` : 'Notifications'}
                aria-haspopup="true"
                aria-expanded={open}
            >
                <Bell size={16} aria-hidden="true" />
                {unreadCount > 0 && <span className="sk-notif__badge">{badge}</span>}
            </button>

            {open && (
                <div className="sk-notif__panel" role="menu" aria-label="Notifications">
                    <div className="sk-notif__head">
                        <span className="sk-notif__heading">Notifications</span>
                        {unreadCount > 0 && (
                            <button type="button" className="sk-notif__markall" onClick={markAllRead}>
                                <Check size={13} aria-hidden="true" /> Mark all read
                            </button>
                        )}
                    </div>

                    <div className="sk-notif__list">
                        {items.length === 0 ? (
                            <div className="sk-notif__empty">You&rsquo;re all caught up.</div>
                        ) : (
                            items.map((item) => (
                                item.kind === 'notice' ? (
                                    <div key={item.delivery_id} className="sk-notif__item is-notice">
                                        <button
                                            type="button"
                                            className="sk-notif__hit"
                                            onClick={() => onItemClick(item)}
                                        >
                                            <span
                                                className="sk-notif__dot"
                                                style={{ background: SEVERITY_DOT[item.severity] || SEVERITY_DOT.info }}
                                                aria-hidden="true"
                                            />
                                            <span className="sk-notif__content">
                                                <span className="sk-notif__title">{item.title}</span>
                                                {item.body && <span className="sk-notif__text">{item.body}</span>}
                                                {item.action_label && (
                                                    <span className="sk-notif__time">{item.action_label} →</span>
                                                )}
                                            </span>
                                        </button>
                                        <button
                                            type="button"
                                            className="sk-notif__dismiss"
                                            onClick={() => dismissNotice && dismissNotice(item.notice_id)}
                                            aria-label={`Dismiss ${item.title}`}
                                        >
                                            <X size={14} aria-hidden="true" />
                                        </button>
                                    </div>
                                ) : (
                                    <button
                                        key={item.delivery_id}
                                        type="button"
                                        className={`sk-notif__item${item.read ? '' : ' is-unread'}`}
                                        onClick={() => onItemClick(item)}
                                    >
                                        <span
                                            className="sk-notif__dot"
                                            style={{ background: SEVERITY_DOT[item.severity] || SEVERITY_DOT.info }}
                                            aria-hidden="true"
                                        />
                                        <span className="sk-notif__content">
                                            <span className="sk-notif__title">{item.title}</span>
                                            {item.body && <span className="sk-notif__text">{item.body}</span>}
                                            <span className="sk-notif__time">
                                                {timeAgo(item.created_at)}
                                                {item.action_path && <span className="sk-notif__cta"> · {item.action_label || 'Open'} →</span>}
                                            </span>
                                        </span>
                                    </button>
                                )
                            ))
                        )}
                    </div>

                    <button
                        type="button"
                        className="sk-notif__seeall"
                        onClick={() => { setOpen(false); navigate('/notifications'); }}
                    >
                        See all notifications
                    </button>
                </div>
            )}
        </div>
    );
}
