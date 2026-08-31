import { useState, useEffect, useCallback } from 'react';
import { HardDrive } from 'lucide-react';
import api from '../services/cloudflare';
import { Button, Input, EmptyState, useToast } from 'serverkit-sdk';
import { useTranslation } from 'react-i18next';

function StorageSection({
    title,
    emptyHint,
    items,
    error,
    placeholder,
    hint,
    renderItem,
    onCreate,
    onDelete,
    isAdmin,
    busy,
}) {
    const { t } = useTranslation();
    const [value, setValue] = useState('');

    const writeDisabled = !isAdmin || busy;

    const handleCreate = async () => {
        const trimmed = value.trim();
        if (!trimmed) return;
        // Only clear the input when the create succeeds; a throw leaves the text intact.
        await onCreate(trimmed);
        setValue('');
    };

    return (
        <section className="cf-storage__section">
            <h3 className="cf-storage__heading">
                {title} ({error ? 0 : items.length})
            </h3>

            {hint && <p className="cf-storage__hint">{hint}</p>}

            {error ? (
                <p className="cf-storage__error">{error}</p>
            ) : (
                <>
                    <div className="cf-storage__create">
                        <Input
                            value={value}
                            placeholder={placeholder}
                            onChange={(e) => setValue(e.target.value)}
                            disabled={writeDisabled}
                        />
                        <Button
                            size="sm"
                            onClick={handleCreate}
                            disabled={writeDisabled || !value.trim()}
                        >
                            {t('common.actions.add', 'Add')}
                        </Button>
                    </div>

                    {items.length === 0 ? (
                        <p className="cf-storage__hint">{emptyHint}</p>
                    ) : (
                        <ul className="cf-storage__list">
                            {items.map((item) => {
                                const { key, label } = renderItem(item);
                                return (
                                    <li className="cf-storage__item" key={key}>
                                        <code className="cf-storage__name">{label}</code>
                                        <Button
                                            variant="destructive"
                                            size="sm"
                                            onClick={() => onDelete(item)}
                                            disabled={writeDisabled}
                                        >
                                            {t('common.actions.delete', 'Delete')}
                                        </Button>
                                    </li>
                                );
                            })}
                        </ul>
                    )}
                </>
            )}
        </section>
    );
}

export default function StoragePanel({ zoneId, isAdmin }) {
    const { t } = useTranslation();
    const toast = useToast();

    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [data, setData] = useState(null);

    // Tracks any in-flight write so all write controls can disable
    const [working, setWorking] = useState(false);

    const loadData = useCallback(async () => {
        try {
            const res = await api.getCloudflareStorage(zoneId);
            setData(res);
            setError(null);
        } catch (err) {
            setError(err.message);
        }
    }, [zoneId]);

    useEffect(() => {
        let active = true;
        setLoading(true);
        (async () => {
            try {
                const res = await api.getCloudflareStorage(zoneId);
                if (!active) return;
                setData(res);
                setError(null);
            } catch (err) {
                if (active) setError(err.message);
            } finally {
                if (active) setLoading(false);
            }
        })();
        return () => {
            active = false;
        };
    }, [zoneId]);

    const handleCreateR2 = async (name) => {
        setWorking(true);
        try {
            await api.createCloudflareR2Bucket(zoneId, name);
            toast.success(t('app.storagePanel.createdBucket', 'Created bucket "{{name}}"', { name: name }));
            await loadData();
        } catch (err) {
            toast.error(err.message);
            throw err;
        } finally {
            setWorking(false);
        }
    };

    const handleDeleteR2 = async (bucket) => {
        setWorking(true);
        try {
            await api.deleteCloudflareR2Bucket(zoneId, bucket.name);
            toast.success(t('app.storagePanel.deleted', 'Deleted'));
            await loadData();
        } catch (err) {
            toast.error(err.message);
        } finally {
            setWorking(false);
        }
    };

    const handleCreateKv = async (title) => {
        setWorking(true);
        try {
            await api.createCloudflareKvNamespace(zoneId, title);
            toast.success(t('app.storagePanel.createdNamespace', 'Created namespace "{{title}}"', { title: title }));
            await loadData();
        } catch (err) {
            toast.error(err.message);
            throw err;
        } finally {
            setWorking(false);
        }
    };

    const handleDeleteKv = async (namespace) => {
        setWorking(true);
        try {
            await api.deleteCloudflareKvNamespace(zoneId, namespace.id);
            toast.success(t('app.storagePanel.deleted', 'Deleted'));
            await loadData();
        } catch (err) {
            toast.error(err.message);
        } finally {
            setWorking(false);
        }
    };

    const handleCreateD1 = async (name) => {
        setWorking(true);
        try {
            await api.createCloudflareD1Database(zoneId, name);
            toast.success(t('app.storagePanel.createdDatabase', 'Created database "{{name}}"', { name: name }));
            await loadData();
        } catch (err) {
            toast.error(err.message);
            throw err;
        } finally {
            setWorking(false);
        }
    };

    const handleDeleteD1 = async (database) => {
        setWorking(true);
        try {
            await api.deleteCloudflareD1Database(zoneId, database.uuid);
            toast.success(t('app.storagePanel.deleted', 'Deleted'));
            await loadData();
        } catch (err) {
            toast.error(err.message);
        } finally {
            setWorking(false);
        }
    };

    if (loading) {
        return <div className="cf-storage__loading">{t('app.storagePanel.loadingStorage', 'Loading storage…')}</div>;
    }

    if (error) {
        return (
            <EmptyState
                icon={HardDrive}
                title={t('app.storagePanel.storageUnavailable', 'Storage unavailable')}
                description={error}
            />
        );
    }

    const errors = data.errors || {};

    return (
        <div className="cf-storage">
            <StorageSection
                title={t('app.storagePanel.r2Buckets', 'R2 buckets')}
                emptyHint={t('app.storagePanel.noR2BucketsYet', 'No R2 buckets yet.')}
                items={data.r2 || []}
                error={errors.r2}
                placeholder="my-bucket"
                hint={t('app.storagePanel.r2IsS3CompatibleSoA', 'R2 is S3-compatible, so a bucket here can back ServerKit backups later.')}
                renderItem={(b) => ({ key: b.name, label: b.name })}
                onCreate={handleCreateR2}
                onDelete={handleDeleteR2}
                isAdmin={isAdmin}
                busy={working}
            />

            <StorageSection
                title={t('app.storagePanel.kvNamespaces', 'KV namespaces')}
                emptyHint={t('app.storagePanel.noKvNamespacesYet', 'No KV namespaces yet.')}
                items={data.kv || []}
                error={errors.kv}
                placeholder="my-namespace"
                renderItem={(n) => ({ key: n.id, label: n.title })}
                onCreate={handleCreateKv}
                onDelete={handleDeleteKv}
                isAdmin={isAdmin}
                busy={working}
            />

            <StorageSection
                title={t('app.storagePanel.d1Databases', 'D1 databases')}
                emptyHint={t('app.storagePanel.noD1DatabasesYet', 'No D1 databases yet.')}
                items={data.d1 || []}
                error={errors.d1}
                placeholder="my-database"
                renderItem={(d) => ({ key: d.uuid, label: d.name })}
                onCreate={handleCreateD1}
                onDelete={handleDeleteD1}
                isAdmin={isAdmin}
                busy={working}
            />
        </div>
    );
}
