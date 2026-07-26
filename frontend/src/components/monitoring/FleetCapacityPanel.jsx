import { useState, useEffect, useMemo } from 'react';
import { BarChart3, CheckCircle, Download, TrendingUp } from 'lucide-react';
import {
    LineChart, Line, AreaChart, Area, XAxis, YAxis,
    CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import api from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import { Button } from '@/components/ui/button';
import { Pill } from '@/components/ds';
import { CHART_COLORS, METRIC_LABELS } from './fleetMetrics';

// The three fleet-wide questions that only make sense across servers: how do
// these boxes compare, which one is behaving unlike itself, and when does a
// disk run out. Host-scoped gauges live on the Overview tab.
export default function FleetCapacityPanel({ scope, refreshKey = 0 }) {
    const toast = useToast();
    const [servers, setServers] = useState([]);

    // Comparison
    const [selectedServers, setSelectedServers] = useState([]);
    // The top-bar scope is the page's answer to "which host?", so it seeds both
    // controls here — you land on the server you were already looking at.
    const scopedServer = scope && scope !== 'host' ? scope : '';
    const [compMetric, setCompMetric] = useState('cpu');
    const [compPeriod, setCompPeriod] = useState('24h');
    const [compData, setCompData] = useState(null);
    const [comparing, setComparing] = useState(false);

    // Anomalies
    const [anomalies, setAnomalies] = useState([]);

    // Forecast
    const [forecastServer, setForecastServer] = useState(scopedServer);
    const [forecastMetric, setForecastMetric] = useState('disk');
    const [forecast, setForecast] = useState(null);

    useEffect(() => {
        if (!scopedServer) return;
        setForecastServer(scopedServer);
        setSelectedServers((prev) => (prev.includes(scopedServer) ? prev : [...prev, scopedServer]));
    }, [scopedServer]);

    useEffect(() => {
        let cancelled = false;
        api.getServers()
            .then((data) => {
                if (cancelled) return;
                const list = data?.servers || data;
                setServers(Array.isArray(list) ? list : []);
            })
            .catch(() => { if (!cancelled) setServers([]); });
        api.getFleetAnomalies()
            .then((data) => { if (!cancelled) setAnomalies(Array.isArray(data) ? data : []); })
            .catch(() => { if (!cancelled) setAnomalies([]); });
        return () => { cancelled = true; };
    }, [refreshKey]);

    const loadComparison = async () => {
        if (selectedServers.length === 0) return;
        setComparing(true);
        try {
            setCompData(await api.getFleetComparison(selectedServers, compMetric, compPeriod));
        } catch {
            toast.error('Failed to load comparison data');
        } finally {
            setComparing(false);
        }
    };

    const loadForecast = async () => {
        if (!forecastServer) return;
        try {
            setForecast(await api.getCapacityForecast(forecastServer, forecastMetric));
        } catch {
            toast.error('Failed to load forecast');
        }
    };

    const exportCsv = async () => {
        if (selectedServers.length === 0) return;
        try {
            const blob = await api.exportFleetCsv(selectedServers, compMetric, compPeriod);
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `fleet_${compMetric}_${compPeriod}.csv`;
            a.click();
            URL.revokeObjectURL(url);
        } catch {
            toast.error('Export failed');
        }
    };

    const toggleServer = (id) => {
        setSelectedServers((prev) => (
            prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]
        ));
    };

    // Recharts wants one row per timestamp with a column per series; the API
    // returns one series per server, so pivot before rendering.
    const compChartData = useMemo(() => {
        if (!compData?.series?.length) return [];
        const byTime = {};
        compData.series.forEach((s) => {
            s.data.forEach((point) => {
                if (!byTime[point.timestamp]) byTime[point.timestamp] = { timestamp: point.timestamp };
                byTime[point.timestamp][s.name] = point.value;
            });
        });
        return Object.values(byTime).sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    }, [compData]);

    return (
        <div className="monitoring-stack">
            <section className="monitoring-panel">
                <div className="monitoring-panel__header">
                    <h3>Server Comparison</h3>
                    <div>
                        <Button variant="outline" size="sm" onClick={exportCsv} disabled={selectedServers.length === 0}>
                            <Download size={14} /> Export CSV
                        </Button>
                        <Button size="sm" onClick={loadComparison} disabled={selectedServers.length === 0 || comparing}>
                            <BarChart3 size={14} /> {comparing ? 'Comparing…' : 'Compare'}
                        </Button>
                    </div>
                </div>

                <div className="mon-compare-controls">
                    <div className="mon-compare-controls__servers">
                        <span className="mon-field-label">Servers</span>
                        <div className="mon-server-picker">
                            {servers.length === 0 ? (
                                <span className="mon-field-hint">No servers paired yet.</span>
                            ) : servers.map((s) => (
                                <Button
                                    key={s.id}
                                    size="sm"
                                    variant={selectedServers.includes(s.id) ? 'default' : 'ghost'}
                                    onClick={() => toggleServer(s.id)}
                                >
                                    {s.name}
                                </Button>
                            ))}
                        </div>
                    </div>
                    <div className="form-group">
                        <span className="mon-field-label">Metric</span>
                        <select value={compMetric} onChange={(e) => setCompMetric(e.target.value)}>
                            {Object.entries(METRIC_LABELS).map(([k, v]) => (
                                <option key={k} value={k}>{v}</option>
                            ))}
                        </select>
                    </div>
                    <div className="form-group">
                        <span className="mon-field-label">Period</span>
                        <div className="mon-period-switch">
                            {['1h', '6h', '24h', '7d'].map((p) => (
                                <Button
                                    key={p}
                                    size="sm"
                                    variant={compPeriod === p ? 'default' : 'ghost'}
                                    onClick={() => setCompPeriod(p)}
                                >
                                    {p}
                                </Button>
                            ))}
                        </div>
                    </div>
                </div>

                {compChartData.length > 0 && compData?.series ? (
                    <ResponsiveContainer width="100%" height={360}>
                        <AreaChart data={compChartData}>
                            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" />
                            <XAxis
                                dataKey="timestamp"
                                tickFormatter={(v) => new Date(v).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                stroke="var(--text-secondary)"
                                fontSize={12}
                            />
                            <YAxis stroke="var(--text-secondary)" fontSize={12} unit="%" />
                            <Tooltip
                                labelFormatter={(v) => new Date(v).toLocaleString()}
                                contentStyle={{ backgroundColor: 'var(--card-bg)', border: '1px solid var(--border-color)' }}
                            />
                            <Legend />
                            {compData.series.map((s, i) => (
                                <Area
                                    key={s.server_id}
                                    type="monotone"
                                    dataKey={s.name}
                                    stroke={CHART_COLORS[i % CHART_COLORS.length]}
                                    fill={CHART_COLORS[i % CHART_COLORS.length]}
                                    fillOpacity={0.1}
                                    strokeWidth={2}
                                    dot={false}
                                />
                            ))}
                        </AreaChart>
                    </ResponsiveContainer>
                ) : (
                    <p className="mon-panel-hint">
                        Pick two or more servers, then Compare to plot the same metric across all of them.
                    </p>
                )}
            </section>

            <section className="monitoring-panel">
                <div className="monitoring-panel__header">
                    <h3>Anomaly Detection</h3>
                </div>
                {anomalies.length > 0 ? (
                    <div className="mon-table-scroll">
                        <table className="sk-dtable">
                            <thead>
                                <tr>
                                    <th>Server</th>
                                    <th>Metric</th>
                                    <th>Current</th>
                                    <th>Baseline (mean)</th>
                                    <th>Std dev</th>
                                    <th>Z-score</th>
                                    <th>Direction</th>
                                </tr>
                            </thead>
                            <tbody>
                                {anomalies.map((a, i) => (
                                    <tr key={`${a.server_name}-${a.metric}-${i}`}>
                                        <td>{a.server_name}</td>
                                        <td>{METRIC_LABELS[a.metric] || a.metric}</td>
                                        <td className="sk-cell-mono">{a.current_value}%</td>
                                        <td className="sk-cell-mono">{a.mean}%</td>
                                        <td className="sk-cell-mono">{a.stddev}</td>
                                        <td className="sk-cell-mono">{a.z_score}</td>
                                        <td>
                                            <Pill kind={a.direction === 'high' ? 'red' : 'cyan'}>
                                                {a.direction === 'high' ? 'Unusually high' : 'Unusually low'}
                                            </Pill>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <p className="mon-panel-hint">
                        <CheckCircle size={14} /> Every metric is within its own recent baseline.
                    </p>
                )}
            </section>

            <section className="monitoring-panel">
                <div className="monitoring-panel__header">
                    <h3>Capacity Forecast</h3>
                    <Button size="sm" onClick={loadForecast} disabled={!forecastServer}>
                        <TrendingUp size={14} /> Forecast
                    </Button>
                </div>

                <div className="mon-compare-controls">
                    <div className="form-group">
                        <span className="mon-field-label">Server</span>
                        <select value={forecastServer} onChange={(e) => setForecastServer(e.target.value)}>
                            <option value="">Select a server…</option>
                            {servers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                        </select>
                    </div>
                    <div className="form-group">
                        <span className="mon-field-label">Metric</span>
                        <select value={forecastMetric} onChange={(e) => setForecastMetric(e.target.value)}>
                            <option value="disk">Disk</option>
                            <option value="memory">Memory</option>
                            <option value="cpu">CPU</option>
                        </select>
                    </div>
                </div>

                {forecast?.error && <div className="fleet-warnrow">{forecast.error}</div>}

                {forecast && !forecast.error ? (
                    <div className="mon-forecast">
                        <div className="mon-forecast__stats">
                            <div className="fleet-statbox">
                                <span className="mon-field-label">Current</span>
                                <strong>{forecast.current_value}%</strong>
                            </div>
                            <div className="fleet-statbox">
                                <span className="mon-field-label">Growth rate</span>
                                <strong>{forecast.growth_rate_per_day}%/day</strong>
                            </div>
                            <div className="fleet-statbox">
                                <span className="mon-field-label">Trend</span>
                                <strong>{forecast.trend}</strong>
                            </div>
                        </div>

                        {forecast.predictions && (
                            <div className="mon-forecast__predictions">
                                <div className={`fleet-predbox ${forecast.predictions.days_to_90pct === 0 ? 'is-red' : 'is-amber'}`}>
                                    <span className="mon-field-label">Reaches 90%</span>
                                    <strong>
                                        {forecast.predictions.date_90pct || 'N/A'}
                                        {forecast.predictions.days_to_90pct > 0 && (
                                            <em> ({forecast.predictions.days_to_90pct} days)</em>
                                        )}
                                    </strong>
                                </div>
                                <div className="fleet-predbox is-red">
                                    <span className="mon-field-label">Reaches 100%</span>
                                    <strong>
                                        {forecast.predictions.date_100pct || 'N/A'}
                                        {forecast.predictions.days_to_100pct > 0 && (
                                            <em> ({forecast.predictions.days_to_100pct} days)</em>
                                        )}
                                    </strong>
                                </div>
                            </div>
                        )}

                        {forecast.trend_data && (
                            <ResponsiveContainer width="100%" height={280}>
                                <LineChart data={forecast.trend_data}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" />
                                    <XAxis dataKey="date" stroke="var(--text-secondary)" fontSize={11} />
                                    <YAxis stroke="var(--text-secondary)" fontSize={12} unit="%" domain={[0, 100]} />
                                    <Tooltip contentStyle={{ backgroundColor: 'var(--card-bg)', border: '1px solid var(--border-color)' }} />
                                    <Legend />
                                    <Line type="monotone" dataKey="actual" stroke="var(--accent-bright)" strokeWidth={2} dot={false} name="Actual" />
                                    <Line type="monotone" dataKey="trend" stroke="var(--red)" strokeWidth={2} strokeDasharray="5 5" dot={false} name="Trend" />
                                </LineChart>
                            </ResponsiveContainer>
                        )}
                    </div>
                ) : !forecast && (
                    <p className="mon-panel-hint">
                        Pick a server and a metric to project when it runs out of headroom.
                    </p>
                )}
            </section>
        </div>
    );
}
