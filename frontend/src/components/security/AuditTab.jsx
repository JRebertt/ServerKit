import { useState } from 'react';
import { ClipboardCheck } from 'lucide-react';
import api from '../../services/api';
import EmptyState from '@/components/EmptyState';
import { Button } from '@/components/ui/button';
import { ScoreGauge } from '@/components/ds';

const SEVERITY_TONES = {
    pass: 'green',
    critical: 'red',
    warning: 'amber',
    info: 'cyan',
};

const scoreColor = (score) => {
    if (score >= 80) return 'var(--green)';
    if (score >= 60) return 'var(--accent-bright)';
    if (score >= 40) return 'var(--amber)';
    return 'var(--red)';
};

const AuditTab = () => {
    const [audit, setAudit] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const runAudit = async () => {
        setLoading(true);
        setError(null);
        try {
            const data = await api.generateSecurityAudit();
            setAudit(data.audit);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="audit-tab">
            <div className="card">
                <div className="card-header">
                    <h3>Security Audit</h3>
                    <Button variant="default" onClick={runAudit} disabled={loading}>
                        {loading ? 'Running Audit...' : 'Run Audit'}
                    </Button>
                </div>
                <div className="card-body">
                    {error && <div className="alert alert-danger">{error}</div>}

                    {!audit && !loading && (
                        <EmptyState
                            icon={ClipboardCheck}
                            title="Run a security audit to check your server's configuration."
                        />
                    )}

                    {loading && (
                        <div className="loading-state">
                            <div className="spinner"></div>
                            <p>Running security audit...</p>
                        </div>
                    )}

                    {audit && !loading && (
                        <div className="audit-results">
                            <div className="sec-audit-score">
                                <ScoreGauge
                                    value={audit.score}
                                    size={120}
                                    stroke={10}
                                    color={scoreColor(audit.score)}
                                    label="security score"
                                />
                                <div className="sec-audit-meta">Generated {new Date(audit.generated_at).toLocaleString()}</div>
                            </div>

                            {Object.entries(audit.services || {}).map(([service, data]) => (
                                <div key={service} className="audit-section">
                                    <h4>{service.toUpperCase()}</h4>
                                    <div className="sec-finding-list">
                                        {data.findings?.map((finding, idx) => (
                                            <div key={idx} className="sec-finding">
                                                <span className={`sec-state sec-state--${SEVERITY_TONES[finding.severity] || 'gray'}`}>
                                                    {finding.severity}
                                                </span>
                                                <span className="sec-finding__msg">{finding.message}</span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            ))}

                            {audit.recommendations?.length > 0 && (
                                <div className="audit-section recommendations">
                                    <h4>Recommendations</h4>
                                    <ul>
                                        {audit.recommendations.map((rec, idx) => (
                                            <li key={idx}>{rec}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default AuditTab;
