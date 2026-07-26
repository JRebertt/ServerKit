import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import api from '../services/api';
import {
    Check, Database, AlertTriangle, ArrowRight, Download,
    Loader, CheckCircle, XCircle, RotateCcw, Shield
} from 'lucide-react';
import ServerKitLogo from '../components/ServerKitLogo';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const TOTAL_STEPS = 4;
const STEP_TITLES = ['Overview', 'Backup', 'Apply', 'Done'];
// How many pending migrations to show before collapsing the rest behind a toggle.
const MIGRATION_PREVIEW_COUNT = 4;

const DatabaseMigration = () => {
    const { isAuthenticated, isAdmin, needsMigration, migrationInfo, refreshSetupStatus, login } = useAuth();
    const navigate = useNavigate();

    const [currentStep, setCurrentStep] = useState(1);
    const [backupResult, setBackupResult] = useState(null);
    const [backupLoading, setBackupLoading] = useState(false);
    const [applyLoading, setApplyLoading] = useState(false);
    const [applyError, setApplyError] = useState(null);
    const [migrationStatus, setMigrationStatus] = useState(null);
    const [showAllMigrations, setShowAllMigrations] = useState(false);

    // Login form state (for unauthenticated users)
    const [loginEmail, setLoginEmail] = useState('');
    const [loginPassword, setLoginPassword] = useState('');
    const [loginError, setLoginError] = useState('');
    const [loginLoading, setLoginLoading] = useState(false);

    useEffect(() => {
        loadMigrationStatus();
    }, []);

    // Redirect away if no migration needed
    useEffect(() => {
        if (!needsMigration && migrationStatus && !migrationStatus.needs_migration) {
            navigate('/');
        }
    }, [needsMigration, migrationStatus]);

    async function loadMigrationStatus() {
        try {
            const status = await api.getMigrationStatus();
            setMigrationStatus(status);
        } catch (err) {
            console.error('Failed to load migration status:', err);
        }
    }

    async function handleLogin(e) {
        e.preventDefault();
        setLoginError('');
        setLoginLoading(true);
        try {
            await login(loginEmail, loginPassword);
        } catch (err) {
            setLoginError(err.message || 'Login failed');
        } finally {
            setLoginLoading(false);
        }
    }

    async function handleBackup() {
        setBackupLoading(true);
        try {
            const result = await api.createMigrationBackup();
            setBackupResult(result);
        } catch (err) {
            setBackupResult({ success: false, error: err.message });
        } finally {
            setBackupLoading(false);
        }
    }

    async function handleApply() {
        setApplyLoading(true);
        setApplyError(null);
        try {
            await api.applyMigrations();
            setCurrentStep(4);
            await loadMigrationStatus();
        } catch (err) {
            setApplyError(err.message || 'Migration failed');
        } finally {
            setApplyLoading(false);
        }
    }

    async function handleFinish() {
        await refreshSetupStatus();
        navigate('/');
    }

    function renderProgressBar() {
        const items = [];
        for (let i = 1; i <= TOTAL_STEPS; i++) {
            if (i > 1) {
                items.push(
                    <div
                        key={`line-${i}`}
                        className={`wizard-progress-line${i <= currentStep ? ' active' : ''}`}
                    />
                );
            }
            let stepClass = 'wizard-progress-step';
            if (i < currentStep) stepClass += ' completed';
            else if (i === currentStep) stepClass += ' active';

            items.push(
                <div key={`step-${i}`} className={stepClass} title={STEP_TITLES[i - 1]}>
                    {i < currentStep ? <Check size={16} /> : i}
                </div>
            );
        }
        return <div className="wizard-progress">{items}</div>;
    }

    const status = migrationStatus || migrationInfo || {};
    const pendingCount = status.pending_count || 0;
    const pendingMigrations = status.pending_migrations || [];
    // A long-idle install can be dozens of migrations behind. Listing all of them
    // buried the Continue button under a page of scrolling, so show the newest
    // few — the ones that say what you're actually getting — and let the rest be
    // opened deliberately.
    const hiddenCount = Math.max(0, pendingMigrations.length - MIGRATION_PREVIEW_COUNT);
    const shownMigrations = showAllMigrations
        ? pendingMigrations
        : pendingMigrations.slice(-MIGRATION_PREVIEW_COUNT);

    return (
        <div className="setup-wizard migration-wizard">
            <div className="wizard-card">
                <div className="wizard-header">
                    <ServerKitLogo className="wizard-logo" />
                    <h1>Database Update Required</h1>
                    <p>ServerKit needs to update the database before continuing</p>
                </div>

                {renderProgressBar()}

                {/* Step 1: Overview */}
                {currentStep === 1 && (
                    <div className="wizard-step">
                        <div className="wizard-step-title">Update Overview</div>
                        <div className="wizard-step-description">
                            A new version of ServerKit requires database changes.
                            The panel is paused until these are applied.
                        </div>

                        <div className="migration-status-panel">
                            <div className="migration-status-row">
                                <span className="migration-status-label">Current version</span>
                                <code className="migration-status-value">
                                    {status.current_revision ? status.current_revision.substring(0, 12) : 'none'}
                                </code>
                            </div>
                            <div className="migration-status-row">
                                <span className="migration-status-label">Target version</span>
                                <code className="migration-status-value">
                                    {status.head_revision ? status.head_revision.substring(0, 12) : 'unknown'}
                                </code>
                            </div>
                            <div className="migration-status-row">
                                <span className="migration-status-label">Pending updates</span>
                                <span className="migration-status-value">{pendingCount}</span>
                            </div>
                        </div>

                        {status.orphaned_revision && (
                            <div className="wizard-info-banner wizard-info-banner--warn">
                                <AlertTriangle size={20} className="wizard-info-icon" />
                                <p>
                                    This database is stamped at <code>{status.current_revision}</code>,
                                    which does not exist in this build — usually a branch that added a
                                    migration and was then reverted. The schema cannot be upgraded
                                    until it is stamped back to a known revision:
                                    {' '}<code>flask db stamp {status.head_revision || 'head'}</code>
                                </p>
                            </div>
                        )}

                        {pendingMigrations.length > 0 && (
                            <div className="migration-list">
                                <div className="migration-list-head">
                                    <span className="migration-list-title">
                                        {shownMigrations.length === pendingMigrations.length
                                            ? 'Changes to apply'
                                            : `Latest ${shownMigrations.length} of ${pendingMigrations.length} changes`}
                                    </span>
                                    {pendingMigrations.length > MIGRATION_PREVIEW_COUNT && (
                                        <button
                                            type="button"
                                            className="migration-list-toggle"
                                            onClick={() => setShowAllMigrations(v => !v)}
                                        >
                                            {showAllMigrations
                                                ? 'Show less'
                                                : `Show all ${pendingMigrations.length}`}
                                        </button>
                                    )}
                                </div>
                                {/* Scrolls within itself so Continue stays reachable no matter
                                    how far behind the database is. */}
                                <div className={`migration-list-items${showAllMigrations ? ' is-expanded' : ''}`}>
                                    {shownMigrations.map((m, i) => (
                                        <div key={m.revision || i} className="migration-list-item">
                                            <Database size={14} />
                                            <code>{m.revision.substring(0, 12)}</code>
                                            <span>{m.description || 'Schema update'}</span>
                                        </div>
                                    ))}
                                </div>
                                {!showAllMigrations && hiddenCount > 0 && (
                                    <div className="migration-list-more">
                                        + {hiddenCount} earlier {hiddenCount === 1 ? 'update' : 'updates'}, applied first
                                    </div>
                                )}
                            </div>
                        )}

                        {!isAuthenticated && (
                            <div className="migration-login-section">
                                <div className="wizard-step-title">Admin Login Required</div>
                                <p className="wizard-step-description">
                                    Sign in with an admin account to apply the update.
                                </p>
                                <form onSubmit={handleLogin} className="migration-login-form">
                                    {loginError && (
                                        <div className="migration-error-inline">{loginError}</div>
                                    )}
                                    <Input
                                        type="text"
                                        placeholder="Email or username"
                                        value={loginEmail}
                                        onChange={e => setLoginEmail(e.target.value)}
                                        required
                                    />
                                    <Input
                                        type="password"
                                        placeholder="Password"
                                        value={loginPassword}
                                        onChange={e => setLoginPassword(e.target.value)}
                                        required
                                    />
                                    <Button type="submit" className="btn-wizard-next" disabled={loginLoading}>
                                        {loginLoading ? <Loader size={16} className="spin" /> : 'Sign In'}
                                    </Button>
                                </form>
                            </div>
                        )}

                        {isAuthenticated && !isAdmin && (
                            <div className="wizard-info-banner">
                                <AlertTriangle size={20} className="wizard-info-icon" />
                                <p>Only admin users can apply database updates. Please sign in with an admin account.</p>
                            </div>
                        )}

                        <div className="wizard-nav">
                            <div />
                            <Button
                                className="btn-wizard-next"
                                onClick={() => setCurrentStep(2)}
                                // An orphaned revision cannot be upgraded past — offering
                                // Continue would just fail at "Can't locate revision".
                                disabled={!isAuthenticated || !isAdmin || status.orphaned_revision}
                            >
                                Continue <ArrowRight size={16} />
                            </Button>
                        </div>
                    </div>
                )}

                {/* Step 2: Backup */}
                {currentStep === 2 && (
                    <div className="wizard-step">
                        <div className="wizard-step-title">Create Backup</div>
                        <div className="wizard-step-description">
                            We recommend backing up your database before applying updates.
                        </div>

                        <div className="wizard-info-banner">
                            <Shield size={20} className="wizard-info-icon" />
                            <p>
                                A backup allows you to restore your database if anything goes wrong
                                during the update process.
                            </p>
                        </div>

                        {!backupResult && (
                            <div className="migration-backup-actions">
                                <Button
                                    className="btn-wizard-next"
                                    onClick={handleBackup}
                                    disabled={backupLoading}
                                >
                                    {backupLoading ? (
                                        <><Loader size={16} className="spin" /> Creating Backup...</>
                                    ) : (
                                        <><Download size={16} /> Create Backup</>
                                    )}
                                </Button>
                            </div>
                        )}

                        {backupResult && backupResult.success && (
                            <div className="backup-status backup-status--success">
                                <CheckCircle size={20} />
                                <div>
                                    <strong>Backup created successfully</strong>
                                    <code>{backupResult.path}</code>
                                </div>
                            </div>
                        )}

                        {backupResult && !backupResult.success && (
                            <div className="backup-status backup-status--error">
                                <XCircle size={20} />
                                <div>
                                    <strong>Backup failed</strong>
                                    <span>{backupResult.error}</span>
                                </div>
                            </div>
                        )}

                        <div className="wizard-nav">
                            <Button variant="ghost" className="btn-wizard-prev" onClick={() => setCurrentStep(1)}>
                                Back
                            </Button>
                            <div className="migration-nav-right">
                                {!backupResult?.success && (
                                    <Button
                                        variant="link"
                                        onClick={() => setCurrentStep(3)}
                                    >
                                        Skip backup
                                    </Button>
                                )}
                                <Button
                                    className="btn-wizard-next"
                                    onClick={() => setCurrentStep(3)}
                                    disabled={!backupResult?.success}
                                >
                                    Continue <ArrowRight size={16} />
                                </Button>
                            </div>
                        </div>
                    </div>
                )}

                {/* Step 3: Apply */}
                {currentStep === 3 && (
                    <div className="wizard-step">
                        <div className="wizard-step-title">Apply Updates</div>
                        <div className="wizard-step-description">
                            {applyLoading
                                ? 'Applying database updates. Please do not close this page...'
                                : `Ready to apply ${pendingCount} database update${pendingCount !== 1 ? 's' : ''}.`
                            }
                        </div>

                        {!applyLoading && !applyError && (
                            <div className="migration-apply-actions">
                                <Button className="btn-wizard-next" onClick={handleApply}>
                                    <Database size={16} /> Apply Updates
                                </Button>
                            </div>
                        )}

                        {applyLoading && (
                            <div className="migration-progress">
                                <Loader size={32} className="spin" />
                                <span>Updating database schema...</span>
                            </div>
                        )}

                        {applyError && (
                            <div className="migration-error">
                                <XCircle size={20} />
                                <div>
                                    <strong>Update failed</strong>
                                    <span>{applyError}</span>
                                </div>
                                <Button variant="ghost" className="btn-wizard-prev" onClick={handleApply}>
                                    <RotateCcw size={14} /> Retry
                                </Button>
                            </div>
                        )}

                        {!applyLoading && (
                            <div className="wizard-nav">
                                <Button variant="ghost" className="btn-wizard-prev" onClick={() => setCurrentStep(2)}>
                                    Back
                                </Button>
                                <div />
                            </div>
                        )}
                    </div>
                )}

                {/* Step 4: Done */}
                {currentStep === 4 && (
                    <div className="wizard-step">
                        <div className="migration-success">
                            <CheckCircle size={48} />
                            <h2>Database Updated Successfully</h2>
                            <p>
                                All migrations have been applied.
                                {migrationStatus?.current_revision && (
                                    <> Now at revision <code>{migrationStatus.current_revision.substring(0, 12)}</code>.</>
                                )}
                            </p>
                        </div>

                        <div className="wizard-nav">
                            <div />
                            <Button className="btn-wizard-next" onClick={handleFinish}>
                                Continue to ServerKit <ArrowRight size={16} />
                            </Button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default DatabaseMigration;
