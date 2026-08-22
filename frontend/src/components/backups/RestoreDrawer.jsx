import { useState, useEffect } from 'react';
import { Drawer, SegControl } from '@/components/ds';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { RotateCcw, AlertTriangle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

// Right-side slide-over for the backup "Protection" panel: configure and confirm
// a restore. The restore scope can be the whole site, just files, just the
// database, or — for WordPress targets that expose their table list — a hand-
// picked set of tables. Safety options (a pre-restore backup, permission copy,
// optional maintenance mode) ride alongside. Because overwriting live data is
// irreversible, the destructive action is gated behind a typed-confirmation
// ConfirmDialog rather than a plain button.
//
//   <RestoreDrawer run={run} open={open} onClose={close} onConfirm={doRestore}
//                  targetName="my-site" siteTables={tables}
//                  showMaintenanceModeOption />

// Icon sizes are fixed by the drawer-head / inline-affordance conventions used
// across the redesign primitives, so they live as named constants rather than
// magic numbers sprinkled through the JSX.
const HEAD_ICON_SIZE = 18;
const ACTION_ICON_SIZE = 14;
const WARNING_ICON_SIZE = 14;

// Drawer width matches the other Protection-panel slide-overs.
const DRAWER_WIDTH = 520;

// Base scope choices, always available. Database/Selected-tables are appended
// only for WordPress targets (applications are files-only).
const BASE_SCOPE_OPTIONS = [
    { value: 'full', labelKey: 'app.restoreDrawer.fullSite', label: 'Full site' },
    { value: 'files', labelKey: 'app.restoreDrawer.filesOnly', label: 'Files only' },
];

// Labels for provider-declared restore scopes (plan 52 D4): extension backup
// kinds tell the panel which scopes they support via /backups/target-types,
// so the drawer no longer hardcodes which type owns which scope.
const SCOPE_LABELS = {
    full: 'Full site',
    files: 'Files only',
    database: 'Database only',
    tables: 'Selected tables',
};

const RestoreDrawer = ({
    run,
    open,
    onClose,
    onConfirm,
    targetName,
    targetType,
    restoreScopes,
    siteTables,
    showMaintenanceModeOption,
}) => {
    const { t } = useTranslation();
    const [scope, setScope] = useState('full');
    const [tables, setTables] = useState([]);
    const [safetyBackup, setSafetyBackup] = useState(true);
    const [copyPermissions, setCopyPermissions] = useState(false);
    const [maintenanceMode, setMaintenanceMode] = useState(true);
    const [confirmOpen, setConfirmOpen] = useState(false);

    // Re-seed to defaults each time the drawer is opened, so a previous, possibly
    // abandoned configuration never leaks into the next restore.
    useEffect(() => {
        if (!open) return;
        setScope('full');
        setTables([]);
        setSafetyBackup(true);
        setCopyPermissions(false);
        setMaintenanceMode(true);
        setConfirmOpen(false);
    }, [open]);

    const isWordPress = targetType === 'wordpress_site';
    const hasTables = isWordPress && !!siteTables?.length;

    // When the target-types API answered, its provider-declared scopes win;
    // otherwise keep the legacy type-name derivation as the fallback.
    const scopeOptions = Array.isArray(restoreScopes) && restoreScopes.length
        ? restoreScopes
            .filter((s) => s !== 'tables' || (siteTables?.length > 0))
            .map((s) => ({ value: s, label: SCOPE_LABELS[s] || s }))
        : [
            ...BASE_SCOPE_OPTIONS,
            ...(isWordPress ? [{ value: 'database', labelKey: 'app.restoreDrawer.databaseOnly', label: 'Database only' }] : []),
            ...(hasTables ? [{ value: 'tables', labelKey: 'app.restoreDrawer.selectedTables', label: 'Selected tables' }] : []),
        ];

    const toggleTable = (t) => {
        setTables((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));
    };

    // Disable the restore action until there is a run to restore, and — when the
    // scope is a table subset — until at least one table has been chosen.
    const restoreDisabled = !run || (scope === 'tables' && tables.length === 0);

    const handleConfirm = () => {
        setConfirmOpen(false);
        onConfirm({
            scope,
            tables,
            safety_backup: safetyBackup,
            copy_permissions: copyPermissions,
            maintenance_mode: maintenanceMode,
        });
    };

    const subtitle = run?.metadata?.backup_name || (run ? `Backup #${run.id}` : '');

    return (
        <Drawer
            open={open}
            onOpenChange={(v) => !v && onClose()}
            title={t('app.restoreDrawer.restoreBackup', 'Restore backup')}
            subtitle={subtitle}
            icon={<RotateCcw size={HEAD_ICON_SIZE} />}
            width={DRAWER_WIDTH}
        >
            <div className="restore-drawer">
                <div className="restore-drawer__section">
                    <label className="restore-drawer__label">{t('app.restoreDrawer.scope', 'Scope')}</label>
                    <div className="restore-drawer__scope">
                        <SegControl options={scopeOptions} value={scope} onChange={setScope} />
                    </div>
                </div>

                {scope === 'tables' && hasTables && (
                    <div className="restore-drawer__tables">
                        {siteTables.map((t) => (
                            <label key={t}>
                                <input
                                    type="checkbox"
                                    checked={tables.includes(t)}
                                    onChange={() => toggleTable(t)}
                                />
                                {t}
                            </label>
                        ))}
                    </div>
                )}

                <div className="restore-drawer__section">
                    <label className="restore-drawer__label">{t('app.restoreDrawer.safetyOptions', 'Safety options')}</label>
                    <div className="restore-drawer__options">
                        <div className="restore-drawer__option">
                            <Switch
                                id="safety-backup"
                                checked={safetyBackup}
                                onCheckedChange={setSafetyBackup}
                            />
                            <label htmlFor="safety-backup">{t('app.restoreDrawer.createASafetyBackupFirst', 'Create a safety backup first')}</label>
                        </div>
                        <div className="restore-drawer__option">
                            <Switch
                                id="copy-perms"
                                checked={copyPermissions}
                                onCheckedChange={setCopyPermissions}
                            />
                            <label htmlFor="copy-perms">{t('app.restoreDrawer.copyOriginalFilePermissions', 'Copy original file permissions')}</label>
                        </div>
                        {showMaintenanceModeOption && (
                            <div className="restore-drawer__option">
                                <Switch
                                    id="maint"
                                    checked={maintenanceMode}
                                    onCheckedChange={setMaintenanceMode}
                                />
                                <label htmlFor="maint">
                                    {t('app.restoreDrawer.putSiteInMaintenanceModeDuring', 'Put site in maintenance mode during restore')}
                                </label>
                            </div>
                        )}
                    </div>
                </div>

                <p className="restore-drawer__warning">
                    <AlertTriangle size={WARNING_ICON_SIZE} />
                    {t('app.restoreDrawer.thisWillOverwriteTheCurrentSite', 'This will overwrite the current site with the selected backup. This action cannot be undone.')}
                </p>

                <Button
                    variant="destructive"
                    size="sm"
                    disabled={restoreDisabled}
                    onClick={() => setConfirmOpen(true)}
                >
                    <RotateCcw size={ACTION_ICON_SIZE} />
                    {t('common.actions.restore', 'Restore')}
                </Button>

                <ConfirmDialog
                    isOpen={confirmOpen}
                    title={t('app.restoreDrawer.confirmRestore', 'Confirm restore')}
                    message={t('app.restoreDrawer.typeTheNameToConfirmRestoring', 'Type the name to confirm restoring {{value}}. This overwrites current data.', { value: targetName || 'this target' })}
                    confirmText={t('common.actions.restore', 'Restore')}
                    variant="danger"
                    requireConfirmation={targetName || 'restore'}
                    confirmationPlaceholder={targetName}
                    onConfirm={handleConfirm}
                    onCancel={() => setConfirmOpen(false)}
                />
            </div>
        </Drawer>
    );
};

export default RestoreDrawer;
