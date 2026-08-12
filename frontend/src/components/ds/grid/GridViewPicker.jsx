import { useState } from 'react';
import {
    ChevronDown, Star, Copy, Trash2, Plus, MoreVertical, Check, History, AlertTriangle,
} from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';

// The saved-view selector, rendered as the page's own heading rather than yet
// another toolbar button — the view IS what you are looking at, so its name is
// the largest thing on the page and clicking it swaps the whole grid config.
//
// Built-in views ship in code; "My views" are the user's own, persisted through
// /api/v1/views by useTableViews. A modified view shows an asterisk plus an
// inline Save / Reset strip, so tweaking a built-in never silently destroys it.
export function GridViewPicker({ views, counts, onCreate, label = 'items', total }) {
    const [open, setOpen] = useState(false);
    const [menuFor, setMenuFor] = useState(null);
    const [creating, setCreating] = useState(false);
    const [name, setName] = useState('');
    const [fromCurrent, setFromCurrent] = useState(true);

    const active = views.activeView;
    const activeName = active?.name || `All ${label}`;
    const builtins = views.builtinViews || [];
    const mine = views.userViews || [];

    const pick = (view) => { views.applyView(view); setOpen(false); setMenuFor(null); };

    const submitNew = () => {
        if (!name.trim()) return;
        onCreate(name.trim(), fromCurrent);
        setName('');
        setCreating(false);
        setOpen(false);
    };

    const renderRow = (view) => {
        const key = view.builtin ? `builtin:${view.name}` : `user:${view.id}`;
        const isActive = active && (active.builtin ? active.name === view.name : active.id === view.id);
        return (
            <div key={key} className={cn('sk-viewpick__row', isActive && 'is-on')}>
                <button type="button" className="sk-viewpick__rowmain" onClick={() => pick(view)}>
                    <span className="sk-viewpick__dot" data-builtin={view.builtin ? 'true' : 'false'} />
                    <span className="sk-viewpick__nm">{view.name}</span>
                    {view.is_default && <Star size={11} className="sk-viewpick__star" />}
                    {counts && <span className="sk-viewpick__n">{counts(view)}</span>}
                </button>
                {!view.builtin && (
                    <Popover
                        open={menuFor === key}
                        onOpenChange={(o) => setMenuFor(o ? key : null)}
                    >
                        <PopoverTrigger asChild>
                            <button type="button" className="sk-viewpick__cog" aria-label={`${view.name} options`}>
                                <MoreVertical size={14} />
                            </button>
                        </PopoverTrigger>
                        <PopoverContent align="end" sideOffset={4} className="ui-popover-panel sk-gridmenu">
                            <button
                                type="button"
                                className="sk-gridmenu__opt"
                                onClick={() => { views.toggleDefault(view); setMenuFor(null); }}
                            >
                                <Star size={13} />{view.is_default ? 'Unset as default' : 'Make default'}
                            </button>
                            <button
                                type="button"
                                className="sk-gridmenu__opt"
                                onClick={() => { pick(view); onCreate(`${view.name} copy`, true); setMenuFor(null); }}
                            >
                                <Copy size={13} />Duplicate view
                            </button>
                            <div className="sk-gridmenu__sep" />
                            <button
                                type="button"
                                className="sk-gridmenu__opt is-danger"
                                onClick={() => { views.removeView(view); setMenuFor(null); }}
                            >
                                <Trash2 size={13} />Delete view
                            </button>
                        </PopoverContent>
                    </Popover>
                )}
            </div>
        );
    };

    return (
        <div className="sk-viewbar">
            <Popover open={open} onOpenChange={setOpen}>
                <PopoverTrigger asChild>
                    <button type="button" className={cn('sk-viewpick', open && 'is-open')}>
                        <span className="sk-viewpick__title">{activeName}</span>
                        {views.isDirty && <span className="sk-viewpick__ast">*</span>}
                        <ChevronDown size={16} />
                    </button>
                </PopoverTrigger>
                <PopoverContent align="start" sideOffset={6} className="ui-popover-panel sk-gridmenu sk-viewpick__menu">
                    {!!builtins.length && <div className="sk-gridmenu__head">Built in</div>}
                    {builtins.map(renderRow)}
                    <div className="sk-gridmenu__head">My views</div>
                    {mine.length ? mine.map(renderRow) : (
                        <div className="sk-gridmenu__note">
                            No personal views yet — tune the grid, then save it here.
                        </div>
                    )}
                    <div className="sk-gridmenu__sep" />
                    {creating ? (
                        <>
                            <div className="sk-gridmenu__mini sk-gridmenu__mini--input">
                                <input
                                    autoFocus
                                    value={name}
                                    placeholder="e.g. Cloudflare prod"
                                    onChange={(e) => setName(e.target.value)}
                                    onKeyDown={(e) => {
                                        if (e.key === 'Enter') submitNew();
                                        if (e.key === 'Escape') setCreating(false);
                                    }}
                                />
                            </div>
                            <button
                                type="button"
                                className={cn('sk-gridmenu__opt', fromCurrent && 'is-on')}
                                onClick={() => setFromCurrent((v) => !v)}
                            >
                                <span className="sk-gridmenu__box"><Check size={11} /></span>
                                Start from current filters &amp; columns
                            </button>
                            <div className="sk-gridmenu__foot">
                                <button type="button" onClick={() => setCreating(false)}>Cancel</button>
                                <button type="button" className="is-primary" disabled={!name.trim()} onClick={submitNew}>
                                    Create
                                </button>
                            </div>
                        </>
                    ) : (
                        <button type="button" className="sk-gridmenu__opt" onClick={() => setCreating(true)}>
                            <Plus size={13} />Save current view…
                        </button>
                    )}
                </PopoverContent>
            </Popover>

            {total != null && (
                <span className="sk-viewbar__count">{total}</span>
            )}

            {views.isDirty && (
                <div className="sk-viewbar__dirty">
                    <AlertTriangle size={13} />
                    Unsaved
                    <button type="button" onClick={views.resetView}>
                        <History size={12} />Reset
                    </button>
                    <button
                        type="button"
                        className="is-primary"
                        onClick={() => {
                            if (active && !active.builtin) views.updateActiveView();
                            else setOpen(true);
                        }}
                    >
                        {active && !active.builtin ? 'Save' : 'Save as…'}
                    </button>
                </div>
            )}
        </div>
    );
}

export default GridViewPicker;
