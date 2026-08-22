import { Checkbox } from '@/components/ui/checkbox';
import { useTranslation } from 'react-i18next';

const PERMISSION_GROUPS = [
    {
        labelKey: 'app.permissionEditor.infrastructure', label: 'Infrastructure',
        features: ['applications', 'databases', 'docker', 'domains', 'servers']
    },
    {
        labelKey: 'app.permissionEditor.operations', label: 'Operations',
        features: ['files', 'monitoring', 'backups', 'cron', 'security', 'email', 'git']
    },
    {
        labelKey: 'common.labels.system', label: 'System',
        features: ['terminal', 'users', 'settings']
    }
];

const FEATURE_LABELS = {
    applications: 'Applications',
    databases: 'Databases',
    docker: 'Docker',
    domains: 'Domains',
    servers: 'Servers',
    files: 'File Manager',
    monitoring: 'Monitoring',
    backups: 'Backups',
    cron: 'Cron Jobs',
    security: 'Security',
    email: 'Email',
    git: 'Git',
    terminal: 'Terminal',
    users: 'Users',
    settings: 'Settings'
};

const PermissionEditor = ({ permissions = {}, onChange, disabled = false }) => {
    const { t } = useTranslation();
    function handleToggle(feature, level) {
        const current = permissions[feature] || { read: false, write: false };
        const updated = { ...permissions };

        if (level === 'read') {
            const newRead = !current.read;
            updated[feature] = {
                read: newRead,
                write: newRead ? current.write : false // Disable write if read is off
            };
        } else {
            const newWrite = !current.write;
            updated[feature] = {
                read: newWrite ? true : current.read, // Enable read if write is on
                write: newWrite
            };
        }

        onChange(updated);
    }

    return (
        <div className="permission-editor">
            <div className="permission-header-row">
                <span className="permission-feature-label">{t('app.permissionEditor.feature', 'Feature')}</span>
                <span className="permission-level-label">{t('app.permissionEditor.read', 'Read')}</span>
                <span className="permission-level-label">{t('app.permissionEditor.write', 'Write')}</span>
            </div>
            {PERMISSION_GROUPS.map(group => (
                <div key={group.label} className="permission-group">
                    <div className="permission-group-label">{group.label}</div>
                    {group.features.map(feature => {
                        const featurePerms = permissions[feature] || { read: false, write: false };
                        return (
                            <div key={feature} className="permission-row">
                                <span className="permission-feature-name">
                                    {FEATURE_LABELS[feature]}
                                </span>
                                <div className="permission-checkbox">
                                    <Checkbox
                                        checked={!!featurePerms.read}
                                        onCheckedChange={() => handleToggle(feature, 'read')}
                                        disabled={disabled}
                                    />
                                </div>
                                <div className="permission-checkbox">
                                    <Checkbox
                                        checked={!!featurePerms.write}
                                        onCheckedChange={() => handleToggle(feature, 'write')}
                                        disabled={disabled}
                                    />
                                </div>
                            </div>
                        );
                    })}
                </div>
            ))}
        </div>
    );
};

export default PermissionEditor;
