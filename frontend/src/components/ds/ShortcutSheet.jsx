import Modal from '../Modal';

const MODIFIER_LABELS = {
    alt: 'Alt',
    ctrl: 'Ctrl',
    ctrlOrMeta: 'Ctrl/Cmd',
    meta: 'Cmd',
    shift: 'Shift',
};

function formatShortcut(shortcut) {
    const modifiers = ['ctrlOrMeta', 'ctrl', 'meta', 'alt', 'shift']
        .filter((modifier) => shortcut[modifier])
        .map((modifier) => MODIFIER_LABELS[modifier]);
    const key = shortcut.key === ' ' ? 'Space' : String(shortcut.key);
    return [...modifiers, key].join('+');
}

export default function ShortcutSheet({ open, onClose, title, commands = [] }) {
    const visibleCommands = commands.filter((command) => command.label);

    return (
        <Modal open={open} onClose={onClose} title={title} size="sm">
            <dl className="sk-shortcuts">
                {visibleCommands.map((command) => (
                    <div className="sk-shortcuts__row" key={command.id}>
                        <dt>{command.label}</dt>
                        <dd>
                            {command.keys.map((shortcut) => (
                                <kbd key={formatShortcut(shortcut)}>{formatShortcut(shortcut)}</kbd>
                            ))}
                        </dd>
                    </div>
                ))}
            </dl>
        </Modal>
    );
}
