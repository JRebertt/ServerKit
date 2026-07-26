import { useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import { deriveWidgetTitle, getWidgetType, useWidgetTypes } from '../widgets/registry';
import { WidgetBody } from '../widgets/renderers';

/**
 * Modal that blows one widget up to a comfortable reading size. Escape or a
 * click on the scrim closes it; the panel takes focus on open so keyboard users
 * land inside the dialog rather than back at the top of the board.
 */
export function WidgetFullscreen({ widget, type, ctx, onClose }) {
    const panelRef = useRef(null);
    const types = useWidgetTypes();

    useEffect(() => {
        const onKeyDown = (event) => { if (event.key === 'Escape') onClose?.(); };
        window.addEventListener('keydown', onKeyDown);
        panelRef.current?.focus();
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [onClose]);

    if (!widget) return null;

    const resolved = type || getWidgetType(types, widget.type);
    const title = deriveWidgetTitle(widget, resolved);

    return (
        <>
            {/* Escape and the header's close button are the accessible paths;
                the scrim is a pointer convenience only. */}
            <div className="skw-full__scrim" aria-hidden="true" onClick={onClose} />
            <div
                className="skw-full"
                ref={panelRef}
                role="dialog"
                aria-modal="true"
                aria-label={title}
                tabIndex={-1}
            >
                {/* Same frame chrome as on the board — `.skw-full .skw-frame`
                    restyles it for the larger surface. */}
                <div className="skw-frame">
                    <div className="skw-frame__head">
                        <span className="skw-frame__title">{title}</span>
                        <div className="skw-frame__actions">
                            <button
                                type="button"
                                className="skw-iconbtn skw-iconbtn--bare"
                                title="Close"
                                aria-label="Close fullscreen widget"
                                onClick={onClose}
                            >
                                <X size={15} />
                            </button>
                        </div>
                    </div>
                    <div className="skw-frame__body">
                        <WidgetBody widget={widget} ctx={ctx} />
                    </div>
                </div>
            </div>
        </>
    );
}

export default WidgetFullscreen;
