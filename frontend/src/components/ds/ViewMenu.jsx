import { useState } from 'react';
import { LayoutList, Star, Trash2, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { useToast } from '@/contexts/ToastContext';

// Saved-view picker (CRM style: Twenty view switcher / Frappe view dropdown).
// Lists built-in views plus the user's saved views for the page; clicking a
// row applies it, the star toggles the per-user default, and the footer saves
// the table's current state as a new view. The trigger shows the active
// view's name.
//
//   const views = useTableViews({ page, builtinViews, capture, apply });
//   <ViewMenu views={views} />
export function ViewMenu({ views, className }) {
    const {
        builtinViews, userViews, activeView, isDirty,
        applyView, saveView, updateActiveView, toggleDefault, removeView, resetView,
    } = views;
    const toast = useToast();
    const [open, setOpen] = useState(false);
    const [name, setName] = useState('');
    const [saving, setSaving] = useState(false);

    const handleSave = async () => {
        const trimmed = name.trim();
        if (!trimmed || saving) return;
        setSaving(true);
        try {
            await saveView(trimmed);
            setName('');
            toast.success(`View "${trimmed}" saved`);
        } catch (err) {
            toast.error(err?.data?.error || err?.message || 'Could not save the view');
        } finally {
            setSaving(false);
        }
    };

    const handleUpdate = async () => {
        try {
            await updateActiveView();
            toast.success(`View "${activeView.name}" updated`);
        } catch (err) {
            toast.error(err?.data?.error || err?.message || 'Could not update the view');
        }
    };

    const handleDelete = async (view) => {
        try {
            await removeView(view);
            toast.success(`View "${view.name}" deleted`);
        } catch (err) {
            toast.error(err?.data?.error || err?.message || 'Could not delete the view');
        }
    };

    const isActive = (view) => activeView && activeView.name === view.name
        && activeView.builtin === !!view.builtin;

    const row = (view) => (
        <div
            key={view.builtin ? `b-${view.name}` : `u-${view.id}`}
            className={cn('sk-viewmenu__row', isActive(view) && 'is-active')}
        >
            <button
                type="button"
                className="sk-viewmenu__apply"
                onClick={() => { applyView(view); setOpen(false); }}
            >
                {isActive(view) && <Check size={13} aria-hidden="true" />}
                <span className="sk-viewmenu__name">{view.name}</span>
            </button>
            {!view.builtin && (
                <>
                    <button
                        type="button"
                        className={cn('sk-viewmenu__star', view.is_default && 'is-on')}
                        onClick={() => toggleDefault(view)}
                        title={view.is_default ? 'Remove as default' : 'Set as default view'}
                        aria-label={view.is_default ? 'Remove as default' : 'Set as default view'}
                        aria-pressed={view.is_default}
                    >
                        <Star size={13} />
                    </button>
                    <button
                        type="button"
                        className="sk-viewmenu__delete"
                        onClick={() => handleDelete(view)}
                        title={`Delete "${view.name}"`}
                        aria-label={`Delete view ${view.name}`}
                    >
                        <Trash2 size={13} />
                    </button>
                </>
            )}
        </div>
    );

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
                <Button
                    variant="outline"
                    size="sm"
                    className={cn('sk-filter-btn', activeView && 'sk-filter-btn--active', className)}
                >
                    <LayoutList aria-hidden="true" />
                    {activeView ? activeView.name : 'Views'}
                    {isDirty && <span className="sk-viewmenu__dot" title="Modified — not saved to this view" />}
                </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="sk-tablemenu sk-viewmenu">
                {builtinViews.length > 0 && (
                    <>
                        <div className="sk-tablemenu__title">Built in</div>
                        <div className="sk-tablemenu__list">{builtinViews.map(row)}</div>
                    </>
                )}
                <div className="sk-tablemenu__title">Saved views</div>
                {userViews.length === 0 ? (
                    <div className="sk-tablemenu__empty">
                        No saved views yet — tune the table, then save it below.
                    </div>
                ) : (
                    <div className="sk-tablemenu__list">{userViews.map(row)}</div>
                )}
                {isDirty && activeView && (
                    <div className="sk-viewmenu__update">
                        {!activeView.builtin && (
                            <Button variant="ghost" size="sm" onClick={handleUpdate}>
                                Update &ldquo;{activeView.name}&rdquo; with changes
                            </Button>
                        )}
                        <Button variant="ghost" size="sm" onClick={resetView}>
                            Reset to saved
                        </Button>
                    </div>
                )}
                <div className="sk-viewmenu__save">
                    <input
                        type="text"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter') handleSave(); }}
                        placeholder="Save current as…"
                        aria-label="New view name"
                        maxLength={120}
                    />
                    <Button size="sm" onClick={handleSave} disabled={!name.trim() || saving}>
                        Save
                    </Button>
                </div>
            </PopoverContent>
        </Popover>
    );
}

export default ViewMenu;
