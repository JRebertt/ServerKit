/* eslint-disable no-restricted-syntax --
 * The style guide demonstrates the raw elements and legacy classes that the
 * design-system rules exist to discourage — showing a bare <button> next to the
 * shared <Button> is the entire point of the page. Left un-suppressed it
 * contributed 165 of ~950 no-restricted-syntax warnings, i.e. one file hiding
 * the real drift in every other file behind it.
 */
import { useState } from 'react';
import useTabParam from '../hooks/useTabParam';
import { useLogsDrawer } from '../contexts/LogsDrawerContext';
import {
    Palette, Type, Box, Layout, Square, ToggleLeft, AlertTriangle,
    Info, CheckCircle, XCircle, Bell, Search, Plus, Trash2, Edit3,
    Download, Upload, RefreshCw, Settings, Eye, EyeOff, Copy, Star,
    ChevronDown, ChevronRight, ExternalLink, Server, Database, Globe,
    Shield, Lock, Zap, Activity, BarChart3, Cloud, Terminal, Layers,
    Inbox, Table, AlertCircle, FileText, Monitor, Key, FolderOpen,
    GitBranch, Package, HardDrive, Wifi, WifiOff
} from 'lucide-react';
import Modal from '../components/Modal';
import { ConfirmDialog } from '../components/ConfirmDialog';
import StatusBadge from '../components/StatusBadge';
import EmptyState from '../components/EmptyState';
import { PageSkeleton, PAGE_SKELETON_VARIANTS } from '../components/PageSkeleton';
import { Spinner } from '../components/Spinner';
import { StatCard, StatsGrid } from '../components/StatCard';
import { DangerZone } from '../components/DangerZone';
import { InfoList, InfoItem } from '../components/InfoList';
import { ProgressBar } from '../components/ProgressBar';
import { MetricRow, MetricItem } from '../components/MetricRow';
import { LogViewer } from '../components/LogViewer';
import { ProcessTable, ProcessDetailsPanel } from '../components/ProcessTable';
import { ServiceCard, ServicesGrid } from '../components/ServiceCard';
import { JournalControls } from '../components/JournalControls';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import {
    Sheet, SheetContent, SheetHeader, SheetFooter, SheetTitle, SheetDescription, SheetClose,
} from '@/components/ui/sheet';

const SECTIONS = [
    { id: 'colors', label: 'Colors', icon: Palette },
    { id: 'typography', label: 'Typography', icon: Type },
    { id: 'spacing', label: 'Spacing & Radius', icon: Box },
    { id: 'buttons', label: 'Buttons', icon: Square },
    { id: 'forms', label: 'Forms', icon: ToggleLeft },
    { id: 'tables', label: 'Tables', icon: Table },
    { id: 'cards', label: 'Cards & Stats', icon: Layout },
    { id: 'badges', label: 'Badges & Status', icon: Shield },
    { id: 'alerts', label: 'Alerts & Errors', icon: AlertCircle },
    { id: 'modals', label: 'Modals & Dialogs', icon: Layers },
    { id: 'tabs', label: 'Tabs', icon: ChevronRight },
    { id: 'lists', label: 'Lists & Info', icon: Database },
    { id: 'feedback', label: 'Feedback & Loading', icon: Activity },
    { id: 'empty', label: 'States', icon: Inbox },
    { id: 'pageheaders', label: 'Page Headers', icon: FileText },
    { id: 'patterns', label: 'Page Patterns', icon: Monitor },
    { id: 'utilities', label: 'Utilities', icon: Zap },
];

const SECTION_IDS = SECTIONS.map(s => s.id);
const MANY_TAB_ITEMS = [
    ['overview', 'Overview'],
    ['docker', 'Docker'],
    ['metrics', 'Metrics'],
    ['settings', 'Settings'],
    ['cron', 'Cron Jobs'],
    ['packages', 'Packages'],
    ['services', 'Services'],
    ['security', 'Security'],
    ['cloudflared', 'Cloudflared'],
    ['terminal', 'Terminal'],
    ['logs', 'Logs'],
    ['backups', 'Backups'],
];

export default function StyleGuide() {
    const [activeSection, setActiveSection] = useTabParam('/style-guide', SECTION_IDS, 'colors');
    const { openDrawer } = useLogsDrawer();
    const [modalOpen, setModalOpen] = useState(false);
    const [sheetSide, setSheetSide] = useState('right');
    const [sheetOpen, setSheetOpen] = useState(false);
    const [confirmOpen, setConfirmOpen] = useState(false);
    const [confirmVariant, setConfirmVariant] = useState('danger');
    const [controlledDemoTab, setControlledDemoTab] = useState('general');
    const [halfDemoTab, setHalfDemoTab] = useState('summary');
    const [halfOverflowTab, setHalfOverflowTab] = useState('overview');
    const [inputValue, setInputValue] = useState('');
    const [selectValue, setSelectValue] = useState('');
    const [checkValue, setCheckValue] = useState(false);
    const sections = SECTIONS;

    return (
        <div className="styleguide">
            <div className="page-header">
                <div>
                    <h1>Style Guide</h1>
                    <p className="subtitle">Design system reference &mdash; dev only</p>
                </div>
            </div>

            <Tabs value={activeSection} onValueChange={setActiveSection}>
                <TabsList>
                    {sections.map(s => (
                        <TabsTrigger key={s.id} value={s.id}>
                            <s.icon size={14} />
                            {s.label}
                        </TabsTrigger>
                    ))}
                </TabsList>
            </Tabs>

            <div className="styleguide__content">

                {/* ── COLORS ── */}
                {activeSection === 'colors' && (
                    <div className="space-y-6">
                        <SectionTitle title="Background Colors" />
                        <div className="styleguide__swatch-grid">
                            <Swatch name="--bg-body" label="Body" />
                            <Swatch name="--bg-sidebar" label="Sidebar" />
                            <Swatch name="--bg-card" label="Card" />
                            <Swatch name="--bg-hover" label="Hover" />
                            <Swatch name="--bg-elevated" label="Elevated" />
                            <Swatch name="--bg-secondary" label="Secondary" />
                            <Swatch name="--bg-tertiary" label="Tertiary" />
                        </div>

                        <SectionTitle title="Border Colors" />
                        <div className="styleguide__swatch-grid">
                            <Swatch name="--border-default" label="Default" />
                            <Swatch name="--border-subtle" label="Subtle" />
                            <Swatch name="--border-active" label="Active" />
                            <Swatch name="--border-hover" label="Hover" />
                        </div>

                        <SectionTitle title="Text Colors" />
                        <div className="styleguide__swatch-grid">
                            <Swatch name="--text-primary" label="Primary" text />
                            <Swatch name="--text-secondary" label="Secondary" text />
                            <Swatch name="--text-tertiary" label="Tertiary" text />
                        </div>

                        <SectionTitle title="Accent Colors" />
                        <div className="styleguide__swatch-grid">
                            <Swatch name="--accent-primary" label="Primary" />
                            <Swatch name="--accent-hover" label="Hover" />
                            <Swatch name="--accent-glow" label="Glow" />
                        </div>

                        <SectionTitle title="Semantic Colors" />
                        <div className="styleguide__swatch-grid">
                            <SwatchStatic color="#10b981" label="Success" token="$success" />
                            <SwatchStatic color="rgba(16,185,129,0.1)" label="Success BG" token="$success-bg" />
                            <SwatchStatic color="#f59e0b" label="Warning" token="$warning" />
                            <SwatchStatic color="rgba(245,158,11,0.1)" label="Warning BG" token="$warning-bg" />
                            <SwatchStatic color="#ef4444" label="Danger" token="$danger" />
                            <SwatchStatic color="rgba(239,68,68,0.1)" label="Danger BG" token="$danger-bg" />
                            <SwatchStatic color="#3b82f6" label="Info" token="$info" />
                            <SwatchStatic color="rgba(59,130,246,0.1)" label="Info BG" token="$info-bg" />
                        </div>

                        <SectionTitle title="Brand Colors" />
                        <div className="styleguide__swatch-grid">
                            <SwatchStatic color="#f29111" label="MySQL" token="$color-mysql" />
                            <SwatchStatic color="#336791" label="PostgreSQL" token="$color-postgresql" />
                            <SwatchStatic color="#2496ed" label="Docker" token="$color-docker" />
                            <SwatchStatic color="#777bb4" label="PHP" token="$color-php" />
                            <SwatchStatic color="#3776ab" label="Python" token="$color-python" />
                            <SwatchStatic color="#21759b" label="WordPress" token="$color-wordpress" />
                        </div>
                    </div>
                )}

                {/* ── TYPOGRAPHY ── */}
                {activeSection === 'typography' && (
                    <div className="space-y-6">
                        <SectionTitle title="Font Families" />
                        <div className="card" style={{ padding: 24 }}>
                            <p style={{ fontFamily: "'Inter', sans-serif", marginBottom: 16 }}>
                                <span className="text-tertiary text-sm">$font-main:</span><br />
                                The quick brown fox jumps over the lazy dog &mdash; Inter
                            </p>
                            <p className="mono" style={{ fontSize: 14 }}>
                                <span className="text-tertiary text-sm">$font-mono:</span><br />
                                {'const server = createApp(); // JetBrains Mono'}
                            </p>
                        </div>

                        <SectionTitle title="Font Sizes" />
                        <div className="card" style={{ padding: 24 }}>
                            {[
                                ['$font-size-xs', '10px'], ['$font-size-sm', '12px'],
                                ['$font-size-base', '14px'], ['$font-size-md', '16px'],
                                ['$font-size-lg', '18px'], ['$font-size-xl', '20px'],
                                ['$font-size-2xl', '24px'], ['$font-size-3xl', '30px'],
                            ].map(([token, size]) => (
                                <div key={token} className="flex items-center gap-4 mb-2">
                                    <span className="mono text-tertiary" style={{ minWidth: 160 }}>{token}</span>
                                    <span style={{ fontSize: size }}>{size} &mdash; The quick brown fox</span>
                                </div>
                            ))}
                        </div>

                        <SectionTitle title="Font Weights" />
                        <div className="card" style={{ padding: 24 }}>
                            {[['Normal (400)', 400], ['Medium (500)', 500], ['Semibold (600)', 600], ['Bold (700)', 700]].map(([label, weight]) => (
                                <p key={weight} style={{ fontWeight: weight, marginBottom: 8 }}>
                                    {label} &mdash; The quick brown fox jumps over the lazy dog
                                </p>
                            ))}
                        </div>

                        <SectionTitle title="Heading Tags" />
                        <div className="card" style={{ padding: 24 }}>
                            <h1>h1 &mdash; Page Title</h1>
                            <h2>h2 &mdash; Section Title</h2>
                            <h3>h3 &mdash; Card Title</h3>
                            <h4>h4 &mdash; Subsection</h4>
                            <h5>h5 &mdash; Minor heading</h5>
                            <p>p &mdash; Body text paragraph with normal weight and base font size.</p>
                            <p className="text-secondary">p.text-secondary &mdash; Secondary paragraph text.</p>
                            <p className="text-tertiary">p.text-tertiary &mdash; Tertiary/muted paragraph text.</p>
                        </div>

                        <SectionTitle title="Text Utility Classes" />
                        <div className="card" style={{ padding: 24 }}>
                            <p className="text-primary">.text-primary</p>
                            <p className="text-secondary">.text-secondary</p>
                            <p className="text-tertiary">.text-tertiary</p>
                            <p className="text-success">.text-success</p>
                            <p className="text-warning">.text-warning</p>
                            <p className="text-danger">.text-danger</p>
                            <p className="text-accent">.text-accent</p>
                        </div>
                    </div>
                )}

                {/* ── SPACING & RADIUS ── */}
                {activeSection === 'spacing' && (
                    <div className="space-y-6">
                        <SectionTitle title="Spacing Scale" />
                        <div className="card" style={{ padding: 24 }}>
                            {[
                                ['$space-1', 4], ['$space-2', 8], ['$space-3', 12], ['$space-4', 16],
                                ['$space-5', 20], ['$space-6', 24], ['$space-8', 32], ['$space-10', 40],
                                ['$space-12', 48], ['$space-16', 64],
                            ].map(([token, px]) => (
                                <div key={token} className="flex items-center gap-4 mb-3">
                                    <span className="mono text-tertiary" style={{ minWidth: 120 }}>{token}</span>
                                    <span className="mono text-secondary" style={{ minWidth: 50 }}>{px}px</span>
                                    <div className="styleguide__spacing-bar" style={{ width: px, height: 16 }} />
                                </div>
                            ))}
                        </div>

                        <SectionTitle title="Border Radius" />
                        <div className="styleguide__swatch-grid">
                            {[
                                ['$radius-sm', '4px'], ['$radius-md', '6px'], ['$radius-lg', '8px'],
                                ['$radius-xl', '12px'], ['$radius-2xl', '16px'], ['$radius-full', '9999px'],
                            ].map(([token, val]) => (
                                <div key={token} className="card flex flex-col items-center gap-3" style={{ padding: 20 }}>
                                    <div className="styleguide__radius-box" style={{ borderRadius: val }} />
                                    <span className="mono text-sm text-tertiary">{token}</span>
                                    <span className="text-sm text-secondary">{val}</span>
                                </div>
                            ))}
                        </div>

                        <SectionTitle title="Shadows" />
                        <div className="styleguide__swatch-grid">
                            {['sm', 'md', 'lg'].map(size => (
                                <div key={size} className="card flex flex-col items-center gap-3" style={{ padding: 20 }}>
                                    <div className="styleguide__shadow-box" style={{ boxShadow: `var(--shadow-${size})` }} />
                                    <span className="mono text-sm text-tertiary">$shadow-{size}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* ── BUTTONS ── */}
                {activeSection === 'buttons' && (
                    <div className="space-y-6">
                        <SectionTitle title="Button Variants" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="flex flex-wrap gap-3 mb-6">
                                <Button><Plus size={16} /> Primary</Button>
                                <Button variant="outline"><Edit3 size={16} /> Outline</Button>
                                <Button variant="destructive"><Trash2 size={16} /> Destructive</Button>
                                <Button variant="ghost"><Eye size={16} /> Ghost</Button>
                                <Button variant="secondary"><Settings size={16} /> Secondary</Button>
                            </div>
                            <div className="flex flex-wrap gap-3">
                                <Button disabled>Disabled Primary</Button>
                                <Button variant="outline" disabled>Disabled Outline</Button>
                                <Button variant="destructive" disabled>Disabled Destructive</Button>
                            </div>
                        </div>

                        <SectionTitle title="Button Sizes" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="flex flex-wrap items-center gap-3">
                                <Button size="sm">Small</Button>
                                <Button>Default</Button>
                                <Button size="lg">Large</Button>
                            </div>
                        </div>

                        <SectionTitle title="Icon Buttons" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="flex flex-wrap gap-3">
                                <Button size="icon"><Plus size={16} /></Button>
                                <Button size="icon" variant="outline"><Edit3 size={16} /></Button>
                                <Button size="icon" variant="destructive"><Trash2 size={16} /></Button>
                                <Button size="icon" variant="ghost"><Settings size={16} /></Button>
                                <Button size="icon" variant="ghost"><Copy size={16} /></Button>
                                <Button size="icon" variant="ghost"><RefreshCw size={16} /></Button>
                            </div>
                        </div>

                        <SectionTitle title="Full Width & Loading" />
                        <div className="card" style={{ padding: 24 }}>
                            <Button className="w-full mb-4">Full Width Button</Button>
                            <div className="flex flex-wrap gap-3">
                                <Button disabled>
                                    <Spinner size="sm" />
                                    Saving...
                                </Button>
                                <Button variant="outline" disabled>
                                    <Spinner size="sm" />
                                    Loading...
                                </Button>
                            </div>
                        </div>
                    </div>
                )}

                {/* ── FORMS ── */}
                {activeSection === 'forms' && (
                    <div className="space-y-6">
                        <SectionTitle title="Text Inputs" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="form-group">
                                <label>Default Input</label>
                                <Input type="text" placeholder="Enter text..." value={inputValue} onChange={e => setInputValue(e.target.value)} />
                                <span className="hint">This is a hint text below the input</span>
                            </div>
                            <div className="form-group">
                                <label>Disabled Input</label>
                                <Input type="text" placeholder="Disabled..." disabled />
                            </div>
                        </div>

                        <SectionTitle title="Select & Textarea" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="form-group">
                                <label>Select Dropdown</label>
                                <select className="form-select" value={selectValue} onChange={e => setSelectValue(e.target.value)}>
                                    <option value="">Choose an option...</option>
                                    <option value="1">Option 1</option>
                                    <option value="2">Option 2</option>
                                </select>
                            </div>
                            <div className="form-group">
                                <label>Textarea</label>
                                <Textarea rows={3} placeholder="Enter multiline text..." />
                            </div>
                            <div className="form-group">
                                <label>Code Editor</label>
                                <Textarea className="code-editor" rows={3} placeholder="server { listen 80; }" />
                            </div>
                        </div>

                        <SectionTitle title="Form Row (2-column)" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="form-row">
                                <div className="form-group">
                                    <label>First Name</label>
                                    <Input type="text" placeholder="John" />
                                </div>
                                <div className="form-group">
                                    <label>Last Name</label>
                                    <Input type="text" placeholder="Doe" />
                                </div>
                            </div>
                        </div>

                        <SectionTitle title="Inline Form" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="install-form">
                                <Input type="text" placeholder="Search packages..." />
                                <Button><Search size={16} /> Search</Button>
                            </div>
                        </div>

                        <SectionTitle title="Checkbox Toggle" />
                        <div className="card" style={{ padding: 24 }}>
                            <label className="filter-toggle">
                                <input type="checkbox" checked={checkValue} onChange={e => setCheckValue(e.target.checked)} />
                                <span>Enable feature</span>
                            </label>
                        </div>
                    </div>
                )}

                {/* ── TABLES ── */}
                {activeSection === 'tables' && (
                    <div className="space-y-6">
                        <SectionTitle title="Standard Table (.table)" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="card-header">
                                <h3>SSH Authorized Keys</h3>
                                <div className="card-actions">
                                    <Button size="sm">Add Key</Button>
                                    <Button size="sm" variant="outline">Refresh</Button>
                                </div>
                            </div>
                            <div className="card-body">
                                <table className="table">
                                    <thead>
                                        <tr>
                                            <th>Type</th>
                                            <th>Fingerprint</th>
                                            <th>Comment</th>
                                            <th>Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <tr>
                                            <td><code>ssh-ed25519</code></td>
                                            <td><code>SHA256:abc123def456...</code></td>
                                            <td>deploy@server</td>
                                            <td><Button size="sm" variant="destructive">Remove</Button></td>
                                        </tr>
                                        <tr>
                                            <td><code>ssh-rsa</code></td>
                                            <td><code>SHA256:xyz789ghi012...</code></td>
                                            <td>admin@laptop</td>
                                            <td><Button size="sm" variant="destructive">Remove</Button></td>
                                        </tr>
                                        <tr>
                                            <td><code>ssh-ed25519</code></td>
                                            <td><code>SHA256:mno345pqr678...</code></td>
                                            <td>ci-pipeline</td>
                                            <td><Button size="sm" variant="destructive">Remove</Button></td>
                                        </tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>

                        <SectionTitle title="Table with Badges" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="card-header">
                                <h3>Scan History</h3>
                                <Button size="sm" variant="outline">Refresh</Button>
                            </div>
                            <div className="card-body">
                                <table className="table">
                                    <thead>
                                        <tr>
                                            <th>Date</th>
                                            <th>Directory</th>
                                            <th>Status</th>
                                            <th>Threats</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <tr>
                                            <td>2026-03-29 14:30</td>
                                            <td>/var/www</td>
                                            <td><Badge variant="success">completed</Badge></td>
                                            <td><Badge variant="success">Clean</Badge></td>
                                        </tr>
                                        <tr>
                                            <td>2026-03-28 09:15</td>
                                            <td>/home/deploy</td>
                                            <td><Badge variant="success">completed</Badge></td>
                                            <td><Badge variant="destructive">2 found</Badge></td>
                                        </tr>
                                        <tr>
                                            <td>2026-03-27 22:00</td>
                                            <td>/var/www</td>
                                            <td><Badge variant="warning">cancelled</Badge></td>
                                            <td>&mdash;</td>
                                        </tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>

                        <SectionTitle title="Table with Status Badges" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="card-header">
                                <h3>Firewall Rules</h3>
                            </div>
                            <div className="card-body">
                                <table className="table">
                                    <thead>
                                        <tr>
                                            <th>Port</th>
                                            <th>Protocol</th>
                                            <th>Action</th>
                                            <th>Source</th>
                                            <th>Status</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <tr>
                                            <td><code>22</code></td>
                                            <td>TCP</td>
                                            <td><Badge variant="success">Allow</Badge></td>
                                            <td>Anywhere</td>
                                            <td><StatusBadge status="active" /></td>
                                        </tr>
                                        <tr>
                                            <td><code>80</code></td>
                                            <td>TCP</td>
                                            <td><Badge variant="success">Allow</Badge></td>
                                            <td>Anywhere</td>
                                            <td><StatusBadge status="active" /></td>
                                        </tr>
                                        <tr>
                                            <td><code>3306</code></td>
                                            <td>TCP</td>
                                            <td><Badge variant="destructive">Deny</Badge></td>
                                            <td>External</td>
                                            <td><StatusBadge status="active" /></td>
                                        </tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                )}

                {/* ── CARDS & STATS ── */}
                {activeSection === 'cards' && (
                    <div className="space-y-6">
                        <SectionTitle title="Basic Card" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="card-header">
                                <h3>Card Title</h3>
                                <div className="card-actions">
                                    <Button size="sm" variant="outline">Refresh</Button>
                                    <Button size="sm">Action</Button>
                                </div>
                            </div>
                            <div className="card-body">
                                <p className="text-secondary">Card body content with card-header and card-actions in the header.</p>
                            </div>
                        </div>

                        <SectionTitle title="Stats Grid (StatCard / StatsGrid)" />
                        <StatsGrid>
                            <StatCard icon={Server} iconVariant="apps" label="Applications" value={12} />
                            <StatCard icon={Database} iconVariant="databases" label="Databases" value={5} />
                            <StatCard icon={Cloud} iconVariant="backups" label="Backups" value={24} />
                            <StatCard icon={BarChart3} iconVariant="size" label="Disk Used" value={48} suffix="GB" />
                        </StatsGrid>

                        <SectionTitle title="Metric Row (MetricRow / MetricItem)" />
                        <div className="card" style={{ padding: 24 }}>
                            <MetricRow>
                                <MetricItem label="CPU" value="23%" />
                                <MetricItem label="Memory" value="1.2 GB" />
                                <MetricItem label="Disk" value="48 GB" />
                                <MetricItem label="Network" value="2.4 Mbps" />
                            </MetricRow>
                        </div>

                        <SectionTitle title="Progress Bar (ProgressBar)" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="space-y-4">
                                {[
                                    ['Storage', '48 / 100 GB', 48, null],
                                    ['Memory', '6.2 / 8 GB', 78, '#f59e0b'],
                                    ['CPU', '92%', 92, '#ef4444'],
                                ].map(([label, text, percent, color]) => (
                                    <div key={label}>
                                        <div className="flex justify-between mb-1">
                                            <span className="text-sm text-secondary">{label}</span>
                                            <span className="text-sm mono">{text}</span>
                                        </div>
                                        <ProgressBar percent={percent} color={color} />
                                    </div>
                                ))}
                            </div>
                        </div>

                        <SectionTitle title="Danger Zone (DangerZone)" />
                        <DangerZone
                            title="Delete Application"
                            description="Once deleted, this cannot be undone. All data will be permanently removed."
                            action={<Button variant="destructive"><Trash2 size={16} /> Delete</Button>}
                        />
                    </div>
                )}

                {/* ── BADGES & STATUS ── */}
                {activeSection === 'badges' && (
                    <div className="space-y-6">
                        <SectionTitle title="Status Badges (Component)" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="flex flex-wrap gap-3 mb-4">
                                <StatusBadge status="online" />
                                <StatusBadge status="running" />
                                <StatusBadge status="healthy" />
                                <StatusBadge status="active" />
                                <StatusBadge status="connected" />
                            </div>
                            <div className="flex flex-wrap gap-3 mb-4">
                                <StatusBadge status="offline" />
                                <StatusBadge status="stopped" />
                                <StatusBadge status="error" />
                                <StatusBadge status="failed" />
                                <StatusBadge status="disconnected" />
                            </div>
                            <div className="flex flex-wrap gap-3 mb-4">
                                <StatusBadge status="warning" />
                                <StatusBadge status="degraded" />
                                <StatusBadge status="pending" />
                                <StatusBadge status="building" />
                                <StatusBadge status="deploying" />
                            </div>
                            <div className="flex flex-wrap gap-3">
                                <StatusBadge status="paused" />
                                <StatusBadge status="unknown" />
                            </div>
                        </div>

                        <SectionTitle title="shadcn Badge Variants" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="flex flex-wrap gap-3">
                                <Badge>Default</Badge>
                                <Badge variant="info">Info</Badge>
                                <Badge variant="success">Success</Badge>
                                <Badge variant="warning">Warning</Badge>
                                <Badge variant="destructive">Destructive</Badge>
                                <Badge variant="secondary">Secondary</Badge>
                                <Badge variant="outline">Outline</Badge>
                            </div>
                        </div>

                        <SectionTitle title="App Type / Env / DB Badges" />
                        <div className="card" style={{ padding: 24 }}>
                            <p className="text-sm text-tertiary mb-2">App Types</p>
                            <div className="flex flex-wrap gap-3 mb-4">
                                <span className="app-type">PHP</span>
                                <span className="app-type">Python</span>
                                <span className="app-type">Node.js</span>
                                <span className="app-type">WordPress</span>
                                <span className="app-type">Static</span>
                            </div>
                            <p className="text-sm text-tertiary mb-2">Environments</p>
                            <div className="flex flex-wrap gap-3 mb-4">
                                <span className="env-badge env-production">Production</span>
                                <span className="env-badge env-staging">Staging</span>
                                <span className="env-badge env-development">Development</span>
                            </div>
                            <p className="text-sm text-tertiary mb-2">Database Types</p>
                            <div className="flex flex-wrap gap-3 mb-4">
                                <span className="db-type-badge mysql">MySQL</span>
                                <span className="db-type-badge postgresql">PostgreSQL</span>
                            </div>
                            <p className="text-sm text-tertiary mb-2">SSL</p>
                            <div className="flex flex-wrap gap-3">
                                <span className="ssl-badge"><Lock size={12} /> SSL Active</span>
                            </div>
                        </div>
                    </div>
                )}

                {/* ── ALERTS & ERRORS ── */}
                {activeSection === 'alerts' && (
                    <div className="space-y-6">
                        <SectionTitle title="Alert Banners (.alert)" />
                        <div className="space-y-2">
                            <div className="alert alert-success">
                                <CheckCircle size={16} /> Operation completed successfully.
                            </div>
                            <div className="alert alert-danger">
                                <AlertTriangle size={16} /> Failed to connect to the server.
                            </div>
                            <div className="alert alert-warning">
                                <AlertCircle size={16} /> SSL certificate expires in 7 days.
                            </div>
                            <div className="alert alert-info">
                                <Info size={16} /> A new version is available for update.
                            </div>
                        </div>

                        <SectionTitle title="Alert with Close Button" />
                        <div className="space-y-2">
                            <div className="alert alert-danger">
                                Something went wrong while saving.
                                <button className="alert-close">&times;</button>
                            </div>
                        </div>

                        <SectionTitle title="Error Message (.error-message)" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="error-message">
                                <AlertTriangle size={16} /> This is an inline error message.
                            </div>
                        </div>

                        <SectionTitle title="Error Banner (.error-banner)" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="error-banner">
                                <AlertTriangle size={16} /> This is a full-width error banner.
                            </div>
                        </div>
                    </div>
                )}

                {/* ── MODALS ── */}
                {activeSection === 'modals' && (
                    <div className="space-y-6">
                        <SectionTitle title="Modal Dialog" />
                        <div className="card" style={{ padding: 24 }}>
                            <Button onClick={() => setModalOpen(true)}>
                                Open Modal
                            </Button>
                            <Modal
                                open={modalOpen}
                                onClose={() => setModalOpen(false)}
                                title="Example Modal"
                                footer={<>
                                    <Button variant="outline" onClick={() => setModalOpen(false)}>Cancel</Button>
                                    <Button onClick={() => setModalOpen(false)}>Save Changes</Button>
                                </>}
                            >
                                <p className="text-secondary">Modal body content with a form field.</p>
                                <div className="form-group mt-4">
                                    <label>Example Field</label>
                                    <Input type="text" placeholder="Type something..." />
                                </div>
                            </Modal>
                        </div>

                        <SectionTitle title="Side Drawer (Sheet)" />
                        <p className="text-sm text-secondary mb-2">Right/left-anchored panel built on Radix Dialog. Used for forms like &ldquo;Add Server&rdquo; or &ldquo;Add Service&rdquo; where a slide-in panel is preferred over a centered modal.</p>
                        <div className="card" style={{ padding: 24 }}>
                            <div className="flex flex-wrap gap-3">
                                <Button onClick={() => { setSheetSide('right'); setSheetOpen(true); }}>
                                    <Plus size={16} /> Open Right Drawer
                                </Button>
                                <Button variant="outline" onClick={() => { setSheetSide('left'); setSheetOpen(true); }}>
                                    <Plus size={16} /> Open Left Drawer
                                </Button>
                            </div>
                            <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
                                <SheetContent side={sheetSide}>
                                    <SheetHeader>
                                        <SheetTitle>Add Service</SheetTitle>
                                        <SheetDescription>
                                            Configure a new service. This drawer pattern is the panel-style alternative to a centered modal.
                                        </SheetDescription>
                                    </SheetHeader>
                                    <div className="space-y-4" style={{ padding: '16px 0' }}>
                                        <div className="form-group">
                                            <label>Service name</label>
                                            <Input type="text" placeholder="my-service" />
                                        </div>
                                        <div className="form-group">
                                            <label>Description</label>
                                            <Textarea placeholder="What does this service do?" rows={3} />
                                        </div>
                                    </div>
                                    <SheetFooter>
                                        <SheetClose asChild>
                                            <Button variant="outline">Cancel</Button>
                                        </SheetClose>
                                        <Button onClick={() => setSheetOpen(false)}>Create Service</Button>
                                    </SheetFooter>
                                </SheetContent>
                            </Sheet>
                        </div>

                        <SectionTitle title="Logs Drawer (LogsDrawer)" />
                        <p className="text-sm text-secondary mb-2">Global bottom-pinned drawer for streaming logs. Opens via the LogsDrawer context.</p>
                        <div className="card" style={{ padding: 24 }}>
                            <Button onClick={() => openDrawer({ name: 'sample-service', logPath: '/var/log/syslog', appType: 'logfile' })}>
                                <FileText size={16} /> Open Logs Drawer
                            </Button>
                        </div>

                        <SectionTitle title="Confirm Dialogs" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="flex flex-wrap gap-3">
                                <Button variant="destructive" onClick={() => { setConfirmVariant('danger'); setConfirmOpen(true); }}>Danger</Button>
                                <Button variant="outline" onClick={() => { setConfirmVariant('warning'); setConfirmOpen(true); }}>Warning</Button>
                                <Button variant="outline" onClick={() => { setConfirmVariant('info'); setConfirmOpen(true); }}>Info</Button>
                            </div>
                            <ConfirmDialog
                                isOpen={confirmOpen}
                                title={`${confirmVariant.charAt(0).toUpperCase() + confirmVariant.slice(1)} Action`}
                                message="Are you sure you want to proceed? This action may have consequences."
                                variant={confirmVariant}
                                confirmText="Proceed"
                                onConfirm={() => setConfirmOpen(false)}
                                onCancel={() => setConfirmOpen(false)}
                            />
                        </div>
                    </div>
                )}

                {/* ── TABS ── */}
                {activeSection === 'tabs' && (
                    <div className="space-y-6">
                        <SectionTitle title="Tabs (Basic)" />
                        <div className="card" style={{ padding: 24 }}>
                            <Tabs defaultValue="tab1">
                                <TabsList>
                                    <TabsTrigger value="tab1"><Server size={14} /> General</TabsTrigger>
                                    <TabsTrigger value="tab2"><Shield size={14} /> Security</TabsTrigger>
                                    <TabsTrigger value="tab3"><Activity size={14} /> Monitoring</TabsTrigger>
                                </TabsList>
                                <TabsContent value="tab1">
                                    <p className="text-secondary" style={{ paddingTop: 16 }}>General tab content.</p>
                                </TabsContent>
                                <TabsContent value="tab2">
                                    <p className="text-secondary" style={{ paddingTop: 16 }}>Security tab content.</p>
                                </TabsContent>
                                <TabsContent value="tab3">
                                    <p className="text-secondary" style={{ paddingTop: 16 }}>Monitoring tab content.</p>
                                </TabsContent>
                            </Tabs>
                        </div>

                        <SectionTitle title="Tabs (Controlled)" />
                        <p className="text-sm text-secondary mb-2">Controlled value/onValueChange usage. This should match URL-backed pages behaviorally.</p>
                        <div className="card" style={{ padding: 24 }}>
                            <Tabs value={controlledDemoTab} onValueChange={setControlledDemoTab}>
                                <TabsList>
                                    <TabsTrigger value="general"><Server size={14} /> General</TabsTrigger>
                                    <TabsTrigger value="security"><Shield size={14} /> Security</TabsTrigger>
                                    <TabsTrigger value="monitoring"><Activity size={14} /> Monitoring</TabsTrigger>
                                    <TabsTrigger value="disabled" disabled><Lock size={14} /> Disabled</TabsTrigger>
                                </TabsList>
                                <TabsContent value="general">
                                    <p className="text-secondary" style={{ paddingTop: 16 }}>Controlled general content.</p>
                                </TabsContent>
                                <TabsContent value="security">
                                    <p className="text-secondary" style={{ paddingTop: 16 }}>Controlled security content.</p>
                                </TabsContent>
                                <TabsContent value="monitoring">
                                    <p className="text-secondary" style={{ paddingTop: 16 }}>Controlled monitoring content.</p>
                                </TabsContent>
                            </Tabs>
                        </div>

                        <SectionTitle title="Tabs (Overflow Menu)" />
                        <p className="text-sm text-secondary mb-2">Many tabs force the overflow menu. Selecting an item from the ellipsis must activate the tab and close the popover.</p>
                        <div className="card" style={{ padding: 24 }}>
                            <Tabs defaultValue="overview">
                                <TabsList>
                                    {MANY_TAB_ITEMS.map(([value, label]) => (
                                        <TabsTrigger key={value} value={value}>{label}</TabsTrigger>
                                    ))}
                                </TabsList>
                                {MANY_TAB_ITEMS.map(([value, label]) => (
                                    <TabsContent key={value} value={value}>
                                        <p className="text-secondary" style={{ paddingTop: 16 }}>{label} tab content.</p>
                                    </TabsContent>
                                ))}
                            </Tabs>
                        </div>

                        <SectionTitle title="Tabs (Half + Half Layout)" />
                        <p className="text-sm text-secondary mb-2">Constrained cards catch layout bugs that full-width tabs hide.</p>
                        <div className="styleguide__split-demo">
                            <div className="card" style={{ padding: 24 }}>
                                <Tabs value={halfDemoTab} onValueChange={setHalfDemoTab}>
                                    <TabsList>
                                        <TabsTrigger value="summary">Summary</TabsTrigger>
                                        <TabsTrigger value="activity">Activity</TabsTrigger>
                                    </TabsList>
                                    <TabsContent value="summary">
                                        <p className="text-secondary" style={{ paddingTop: 16 }}>Short two-tab card content.</p>
                                    </TabsContent>
                                    <TabsContent value="activity">
                                        <p className="text-secondary" style={{ paddingTop: 16 }}>Recent activity content.</p>
                                    </TabsContent>
                                </Tabs>
                            </div>

                            <div className="card" style={{ padding: 24 }}>
                                <Tabs value={halfOverflowTab} onValueChange={setHalfOverflowTab}>
                                    <TabsList>
                                        {MANY_TAB_ITEMS.map(([value, label]) => (
                                            <TabsTrigger key={value} value={value}>{label}</TabsTrigger>
                                        ))}
                                    </TabsList>
                                    {MANY_TAB_ITEMS.map(([value, label]) => (
                                        <TabsContent key={value} value={value}>
                                            <p className="text-secondary" style={{ paddingTop: 16 }}>{label} content inside a half-width card.</p>
                                        </TabsContent>
                                    ))}
                                </Tabs>
                            </div>
                        </div>
                    </div>
                )}

                {/* ── LISTS & INFO ── */}
                {activeSection === 'lists' && (
                    <div className="space-y-6">
                        <SectionTitle title="Info List (InfoList / InfoItem)" />
                        <div className="card" style={{ padding: 24 }}>
                            <InfoList>
                                <InfoItem label="Hostname" value="srv-01.example.com" mono />
                                <InfoItem label="IP Address" value="192.168.1.100" mono />
                                <InfoItem label="OS" value="Ubuntu 22.04 LTS" />
                                <InfoItem label="Uptime" value="42 days, 7 hours" />
                                <InfoItem label="Status">
                                    <StatusBadge status="online" />
                                </InfoItem>
                            </InfoList>
                        </div>

                        <SectionTitle title="Environment Variables" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="env-list">
                                {[
                                    ['DATABASE_URL', 'postgresql://localhost:5432/mydb'],
                                    ['SECRET_KEY', '••••••••••'],
                                    ['NODE_ENV', 'production'],
                                ].map(([key, val]) => (
                                    <div key={key} className="env-item">
                                        <span className="env-key">{key}</span>
                                        <span className="env-value">{val}</span>
                                    </div>
                                ))}
                            </div>
                        </div>

                        <SectionTitle title="Package List" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="packages-list">
                                {[['nginx', '1.24.0'], ['postgresql-15', '15.4'], ['redis-server', '7.2.1']].map(([name, ver]) => (
                                    <div key={name} className="package-item">
                                        <span className="package-name">{name}</span>
                                        <span className="package-version">{ver}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                )}

                {/* ── FEEDBACK & LOADING ── */}
                {activeSection === 'feedback' && (
                    <div className="space-y-6">
                        <SectionTitle title="Spinners" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="flex items-center gap-6">
                                {['sm', 'md', 'lg'].map(size => (
                                    <div key={size} className="flex flex-col items-center gap-2">
                                        <Spinner size={size} />
                                        <span className="text-sm text-tertiary">{size}</span>
                                    </div>
                                ))}
                            </div>
                        </div>

                        <SectionTitle title="Spinner Sizes (standalone)" />
                        <p className="text-sm text-tertiary mb-2">Use Spinner directly only inside buttons or inline indicators.</p>

                        <SectionTitle title="Loading skeleton archetypes" />
                        <p className="text-sm text-tertiary mb-2">
                            A skeleton should predict the layout that is about to arrive. Pick the
                            archetype matching the page shape via
                            {' '}<code>&lt;EmptyState loading loadingVariant=&quot;table&quot; /&gt;</code>, or render
                            {' '}<code>&lt;PageSkeleton /&gt;</code> directly. For a pixel-exact skeleton of one
                            region, capture bones instead (<code>npm run capture:skeletons</code>).
                        </p>
                        {PAGE_SKELETON_VARIANTS.map(variant => (
                            <div key={variant} className="sk-gallery">
                                <div className="sk-gallery__name">{variant}</div>
                                <PageSkeleton variant={variant} />
                            </div>
                        ))}
                    </div>
                )}

                {/* ── EMPTY, LOADING & UNAVAILABLE STATES ── */}
                {activeSection === 'empty' && (
                    <div className="space-y-6">
                        <p className="text-secondary text-sm">One component for everything: empty, loading, not-installed, unavailable. Import EmptyState from components/EmptyState.</p>

                        <SectionTitle title="Default (No Data)" />
                        <EmptyState />

                        <SectionTitle title="With Icon, Title, Description, Action" />
                        <EmptyState
                            icon={Server}
                            title="No servers connected"
                            description="Connect your first server to start managing it from the dashboard."
                            action={<Button><Plus size={16} /> Add Server</Button>}
                        />

                        <SectionTitle title="Loading State" />
                        <p className="text-sm text-tertiary mb-2">Pass loading=true. Same component, spinner instead of icon.</p>
                        <EmptyState loading title="Loading services..." />

                        <SectionTitle title="Search Empty" />
                        <EmptyState
                            icon={Search}
                            title="No results found"
                            description="Try adjusting your search or filter criteria."
                        />

                        <SectionTitle title='Large — Not Installed (size="lg")' />
                        <p className="text-sm text-tertiary mb-2">Full-page state for Git, Docker, FTP when not installed.</p>
                        <EmptyState
                            size="lg"
                            icon={GitBranch}
                            title="No Git Server Installed"
                            description="Install Gitea to host and manage your Git repositories locally."
                            action={<Button size="lg"><Download size={16} /> Install Git Server</Button>}
                        />

                        <SectionTitle title='Large — Unavailable (size="lg")' />
                        <EmptyState
                            size="lg"
                            icon={WifiOff}
                            title="Docker Not Available"
                            description="Docker is not installed or not running on this system."
                            action={<Button><RefreshCw size={16} /> Retry Connection</Button>}
                        />

                        <SectionTitle title="Large — Loading" />
                        <EmptyState size="lg" loading title="Loading services..." />

                        <SectionTitle title="Inside a Card (e.g. empty table)" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="card-header">
                                <h3>Scan History</h3>
                                <Button size="sm" variant="outline">Refresh</Button>
                            </div>
                            <div className="card-body">
                                <EmptyState
                                    icon={Search}
                                    title="No scans yet"
                                    description="Start a scan above to check for threats."
                                />
                            </div>
                        </div>

                        <SectionTitle title="Context Grid" />
                        <div className="grid grid-cols-2 gap-4">
                            <EmptyState icon={Database} title="No databases" description="Create your first database." action={<Button size="sm"><Plus size={14} /> Create</Button>} />
                            <EmptyState icon={Globe} title="No domains configured" description="Add a domain to get started." action={<Button size="sm"><Plus size={14} /> Add Domain</Button>} />
                            <EmptyState icon={Key} title="No SSH keys" description="Add an SSH key for secure access." action={<Button size="sm"><Plus size={14} /> Add Key</Button>} />
                            <EmptyState icon={Shield} title="No scan history" description="Run a scan to check for threats." action={<Button size="sm"><Activity size={14} /> Scan</Button>} />
                        </div>
                    </div>
                )}

                {/* ── PAGE HEADERS ── */}
                {activeSection === 'pageheaders' && (
                    <div className="space-y-6">
                        <SectionTitle title="Standard Page Header (.page-header)" />
                        <p className="text-sm text-secondary mb-2">The canonical pattern. Use this for all pages.</p>
                        <div className="card" style={{ padding: 24 }}>
                            <div className="page-header" style={{ margin: 0, padding: 0 }}>
                                <div>
                                    <h1>Page Title</h1>
                                    <p className="subtitle">Description of the page</p>
                                </div>
                                <div className="flex gap-2">
                                    <Button variant="outline"><RefreshCw size={16} /> Refresh</Button>
                                    <Button><Plus size={16} /> Create</Button>
                                </div>
                            </div>
                        </div>

                        <SectionTitle title="Header with Stats Subtitle" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="page-header" style={{ margin: 0, padding: 0 }}>
                                <div>
                                    <h1>Services</h1>
                                    <p className="subtitle">12 services &middot; 9 live</p>
                                </div>
                                <Button><Plus size={16} /> New Service</Button>
                            </div>
                        </div>

                        <SectionTitle title="Header with Conditional Actions" />
                        <div className="card" style={{ padding: 24 }}>
                            <div className="page-header" style={{ margin: 0, padding: 0 }}>
                                <div>
                                    <h1>Git Server</h1>
                                    <p className="subtitle">Self-hosted Git repository management</p>
                                </div>
                                <div className="flex gap-2">
                                    <Button variant="outline"><ExternalLink size={16} /> Open Gitea</Button>
                                    <Button variant="destructive">Stop Server</Button>
                                </div>
                            </div>
                        </div>

                        <SectionTitle title="Card with Header + Actions" />
                        <p className="text-sm text-secondary mb-2">For cards inside pages that need their own header row.</p>
                        <div className="card" style={{ padding: 24 }}>
                            <div className="card-header">
                                <h3>Card Section Title</h3>
                                <div className="card-actions">
                                    <Button size="sm">Add</Button>
                                    <Button size="sm" variant="outline">Refresh</Button>
                                </div>
                            </div>
                            <div className="card-body">
                                <p className="text-secondary">Content below the card header.</p>
                            </div>
                        </div>
                    </div>
                )}

                {/* ── PAGE PATTERNS ── */}
                {activeSection === 'patterns' && (
                    <div className="space-y-6">
                        <SectionTitle title="Card + Table Pattern" />
                        <p className="text-sm text-secondary mb-2">Standard layout for tabular data inside a card.</p>
                        <div className="card" style={{ padding: 24 }}>
                            <div className="card-header">
                                <h3>Authorized Keys</h3>
                                <div className="card-actions">
                                    <Button size="sm"><Plus size={14} /> Add Key</Button>
                                    <Button size="sm" variant="outline"><RefreshCw size={14} /></Button>
                                </div>
                            </div>
                            <div className="card-body">
                                <table className="table">
                                    <thead>
                                        <tr><th>Type</th><th>Fingerprint</th><th>Comment</th><th>Actions</th></tr>
                                    </thead>
                                    <tbody>
                                        <tr>
                                            <td><code>ssh-ed25519</code></td>
                                            <td><code>SHA256:abc123...</code></td>
                                            <td>deploy@server</td>
                                            <td><Button size="sm" variant="destructive">Remove</Button></td>
                                        </tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>

                        <SectionTitle title="Card + Empty State Pattern" />
                        <p className="text-sm text-secondary mb-2">When the card table has no data.</p>
                        <div className="card" style={{ padding: 24 }}>
                            <div className="card-header">
                                <h3>Scan History</h3>
                                <Button size="sm" variant="outline">Refresh</Button>
                            </div>
                            <div className="card-body">
                                <EmptyState
                                    icon={Search}
                                    title="No scans yet"
                                    description="Start a scan above to check for threats."
                                />
                            </div>
                        </div>

                        <SectionTitle title="Card Grid (Scan Options)" />
                        <p className="text-sm text-secondary mb-2">Action cards in a grid for scan/setup type selections.</p>
                        <div className="grid grid-cols-3 gap-4">
                            {[
                                { icon: Zap, title: 'Quick Scan', desc: 'Scan common web directories' },
                                { icon: Globe, title: 'Full Scan', desc: 'Scan entire system (slow)' },
                                { icon: FolderOpen, title: 'Custom Path', desc: 'Scan a specific directory' },
                            ].map(item => (
                                <div key={item.title} className="card" style={{ padding: 24, textAlign: 'center', cursor: 'pointer' }}>
                                    <div className="flex justify-center mb-3">
                                        <div className="stat-icon"><item.icon size={20} /></div>
                                    </div>
                                    <h4 style={{ marginBottom: 4 }}>{item.title}</h4>
                                    <p className="text-sm text-tertiary mb-4">{item.desc}</p>
                                    <Button size="sm">Start Scan</Button>
                                </div>
                            ))}
                        </div>

                        <SectionTitle title="Error Banner at Page Level" />
                        <p className="text-sm text-secondary mb-2">Shown below page header when an API call fails.</p>
                        <div className="alert alert-danger">
                            Failed to load services. Please try again.
                            <button className="alert-close">&times;</button>
                        </div>

                        <SectionTitle title="Log Viewer (LogViewer)" />
                        <p className="text-sm text-secondary mb-2">Split layout: file list sidebar + log content viewer with toolbar.</p>
                        <div style={{ height: 360 }}>
                            <LogViewer
                                files={[
                                    { name: 'error.log', path: '/var/log/nginx/error.log', size: 2516582, type: 'error' },
                                    { name: 'access.log', path: '/var/log/nginx/access.log', size: 19608371, type: 'access' },
                                    { name: 'syslog', path: '/var/log/syslog', size: 5347737, type: 'default' },
                                ]}
                                selectedPath="/var/log/nginx/error.log"
                                getLogIconType={(log) => log.type}
                                content={`[2026-03-29 14:23:01] ERROR connect() failed (111: Connection refused)\n[2026-03-29 14:23:05] WARN  upstream timed out (110: Connection timed out)\n[2026-03-29 14:23:12] INFO  nginx/1.24.0 started\n[2026-03-29 14:23:12] INFO  worker process 1234 started`}
                                searchPattern=""
                                lineCount={100}
                                onLineCountChange={() => {}}
                                autoRefresh={false}
                                onAutoRefreshChange={() => {}}
                                onRefreshFiles={() => {}}
                                onRefreshContent={() => {}}
                                onDownload={() => {}}
                                onClear={() => {}}
                            />
                        </div>

                        <SectionTitle title="Journal Controls (JournalControls)" />
                        <p className="text-sm text-secondary mb-2">Journal tab with service unit chips and priority filter.</p>
                        <div className="card" style={{ padding: 24 }}>
                            <JournalControls
                                unit="nginx"
                                onUnitChange={() => {}}
                                quickUnits={['nginx', 'mysql', 'postgresql', 'docker', 'sshd', 'cron']}
                                lineCount={100}
                                onLineCountChange={() => {}}
                                priority=""
                                onPriorityChange={() => {}}
                                onLoad={() => {}}
                            />
                        </div>

                        <SectionTitle title="Code/Log Viewer Block" />
                        <p className="text-sm text-secondary mb-2">Monospace preformatted content with dark background.</p>
                        <div className="journal-viewer" style={{ height: 160 }}>
                            <pre>{`Mar 29 14:23:01 srv-01 nginx[1234]: worker process started\nMar 29 14:23:02 srv-01 systemd[1]: Started Nginx HTTP Server\nMar 29 14:23:05 srv-01 sshd[5678]: Accepted publickey for deploy\nMar 29 14:23:12 srv-01 cron[91011]: (root) CMD (/usr/local/bin/backup.sh)`}</pre>
                        </div>

                        <SectionTitle title="Process Table (ProcessTable)" />
                        <p className="text-sm text-secondary mb-2">Table with inline usage bars and action buttons.</p>
                        <ProcessTable
                            processes={[
                                { pid: 1234, name: 'nginx', user: 'www-data', cpu_percent: 12.5, memory_percent: 3.2, memory_info: { rss: 134543872 }, status: 'running' },
                                { pid: 5678, name: 'postgres', user: 'postgres', cpu_percent: 8.1, memory_percent: 15.4, memory_info: { rss: 644874240 }, status: 'sleeping' },
                                { pid: 9012, name: 'node', user: 'deploy', cpu_percent: 45.2, memory_percent: 22.1, memory_info: { rss: 924844032 }, status: 'running' },
                            ]}
                            onKill={() => {}}
                            onForceKill={() => {}}
                        />

                        <SectionTitle title="Detail Panel (ProcessDetailsPanel)" />
                        <p className="text-sm text-secondary mb-2">Expandable detail panel below a list/table selection.</p>
                        <ProcessDetailsPanel
                            process={{
                                pid: 1234,
                                name: 'nginx',
                                user: 'www-data',
                                status: 'running',
                                cpu_percent: 12.5,
                                memory_info: { rss: 134543872 },
                                num_threads: 4,
                                create_time: 1711700400,
                                command: "/usr/sbin/nginx -g 'daemon off;'",
                            }}
                            onClose={() => {}}
                        />

                        <SectionTitle title="Service Cards Grid (ServiceCard / ServicesGrid)" />
                        <p className="text-sm text-secondary mb-2">Grid of service cards with status dot, metadata, and action buttons.</p>
                        <ServicesGrid>
                            {[
                                { name: 'nginx', status: 'running', desc: 'HTTP and reverse proxy server', pid: 1234, mem: '48.2 MB' },
                                { name: 'postgresql', status: 'running', desc: 'PostgreSQL database server', pid: 5678, mem: '256 MB' },
                                { name: 'redis-server', status: 'inactive', desc: 'In-memory data structure store', pid: null, mem: null },
                                { name: 'php8.2-fpm', status: 'running', desc: 'PHP FastCGI Process Manager', pid: 3456, mem: '92 MB' },
                            ].map(s => {
                                const meta = [
                                    s.pid && { label: 'PID', value: s.pid },
                                    s.mem && { label: 'Memory', value: s.mem },
                                ].filter(Boolean);
                                return (
                                    <ServiceCard
                                        key={s.name}
                                        name={s.name}
                                        status={s.status}
                                        description={s.desc}
                                        meta={meta}
                                        actions={
                                            <>
                                                {s.status === 'running' ? (
                                                    <>
                                                        <Button size="sm" variant="outline">Restart</Button>
                                                        <Button size="sm" variant="outline">Stop</Button>
                                                    </>
                                                ) : (
                                                    <Button size="sm">Start</Button>
                                                )}
                                                <Button size="sm" variant="outline">Logs</Button>
                                            </>
                                        }
                                    />
                                );
                            })}
                        </ServicesGrid>
                    </div>
                )}

                {/* ── UTILITIES ── */}
                {activeSection === 'utilities' && (
                    <div className="space-y-6">
                        <SectionTitle title="Flex Utilities" />
                        <div className="card" style={{ padding: 24 }}>
                            <p className="text-sm text-tertiary mb-2">.flex .items-center .gap-3</p>
                            <div className="flex items-center gap-3 mb-4" style={{ padding: 8, border: '1px dashed var(--border-active)' }}>
                                <div className="styleguide__util-box">A</div>
                                <div className="styleguide__util-box">B</div>
                                <div className="styleguide__util-box">C</div>
                            </div>
                            <p className="text-sm text-tertiary mb-2">.flex .justify-between</p>
                            <div className="flex justify-between mb-4" style={{ padding: 8, border: '1px dashed var(--border-active)' }}>
                                <div className="styleguide__util-box">Left</div>
                                <div className="styleguide__util-box">Right</div>
                            </div>
                            <p className="text-sm text-tertiary mb-2">.flex .flex-col .gap-2</p>
                            <div className="flex flex-col gap-2" style={{ padding: 8, border: '1px dashed var(--border-active)', maxWidth: 200 }}>
                                <div className="styleguide__util-box">Row 1</div>
                                <div className="styleguide__util-box">Row 2</div>
                            </div>
                        </div>

                        <SectionTitle title="Grid Utilities" />
                        <div className="card" style={{ padding: 24 }}>
                            <p className="text-sm text-tertiary mb-2">.grid .grid-cols-4 .gap-3</p>
                            <div className="grid grid-cols-4 gap-3">
                                {[1,2,3,4,5,6,7,8].map(i => (
                                    <div key={i} className="styleguide__util-box">Cell {i}</div>
                                ))}
                            </div>
                        </div>

                        <SectionTitle title="Z-Index Scale" />
                        <div className="card" style={{ padding: 24 }}>
                            {[
                                ['$z-dropdown', 10], ['$z-sticky', 20], ['$z-fixed', 30],
                                ['$z-modal-backdrop', 40], ['$z-modal', 50], ['$z-tooltip', 60],
                            ].map(([token, val]) => (
                                <div key={token} className="flex items-center gap-4 mb-2">
                                    <span className="mono text-tertiary" style={{ minWidth: 180 }}>{token}</span>
                                    <span className="mono">{val}</span>
                                </div>
                            ))}
                        </div>

                        <SectionTitle title="Breakpoints" />
                        <div className="card" style={{ padding: 24 }}>
                            {[
                                ['$breakpoint-sm', '640px'], ['$breakpoint-md', '768px'],
                                ['$breakpoint-lg', '1024px'], ['$breakpoint-xl', '1280px'],
                            ].map(([token, val]) => (
                                <div key={token} className="flex items-center gap-4 mb-2">
                                    <span className="mono text-tertiary" style={{ minWidth: 180 }}>{token}</span>
                                    <span className="mono">{val}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}

function SectionTitle({ title }) {
    return <h2 className="styleguide__section-title">{title}</h2>;
}

function Swatch({ name, label, text }) {
    const style = text
        ? { color: `var(${name})`, background: 'var(--bg-card)' }
        : { background: `var(${name})` };
    return (
        <div className="styleguide__swatch">
            <div className="styleguide__swatch-preview" style={style}>
                {text && <span style={{ fontSize: 14, fontWeight: 600 }}>Aa</span>}
            </div>
            <span className="styleguide__swatch-label">{label}</span>
            <span className="styleguide__swatch-token">{name}</span>
        </div>
    );
}

function SwatchStatic({ color, label, token }) {
    return (
        <div className="styleguide__swatch">
            <div className="styleguide__swatch-preview" style={{ background: color }} />
            <span className="styleguide__swatch-label">{label}</span>
            <span className="styleguide__swatch-token">{token}</span>
        </div>
    );
}
