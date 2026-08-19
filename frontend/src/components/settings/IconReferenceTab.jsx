import { useState } from 'react';
import {
    Github, FileText, HelpCircle, MessageSquare, Bug, Check, Download, CheckCircle,
    RefreshCw, ExternalLink, Star, X, Code, Search, Container, Globe, BarChart3,
    Database, Shield, Cloud, Video, Music, Image, Home, Server, GitBranch, Workflow,
    HardDrive, Lock, Users, Settings as SettingsIcon, Layers, ChevronDown, Copy, Tag,
    Cpu, AlertTriangle, Info, Activity, Terminal, Play, Square, Trash2, Plus, Package,
    ArrowRight, ArrowLeft, Eye, Save, Clock, Calendar, Edit3, Link, Unlink, Archive,
    Radio, Zap, MemoryStick, Monitor, Sun, Moon, ChevronRight, ChevronUp, LogOut,
    Loader, RotateCcw, FolderOpen, Layout, Palette, Camera, Newspaper, TrendingUp,
    Sparkles, ArrowUpCircle, AlertCircle, XCircle, GitCompare, GitCommit, Rocket,
    Minus, Unlock, ArrowDownLeft, ArrowUpRight
} from 'lucide-react';
import { Input } from '@/components/ui/input';
import { copyToClipboard } from '@/utils/clipboard';

const ICON_CATALOG = {
    'General': {
        Search, X, Check, Copy, Plus, Trash2, Edit3, Save, Eye, Info,
        HelpCircle, AlertTriangle, AlertCircle, ExternalLink, Link, Unlink,
        ChevronDown, ChevronRight, ChevronUp, ArrowRight, ArrowLeft,
        ArrowUpRight, ArrowDownLeft, ArrowUpCircle
    },
    'Status': {
        CheckCircle, XCircle, Loader, RefreshCw, RotateCcw, Activity,
        Zap, Sparkles
    },
    'Files & Data': {
        FileText, FolderOpen, Archive, Download, Package, Database,
        HardDrive, Layers, Tag
    },
    'Media': {
        Image, Video, Music, Camera
    },
    'Development': {
        Code, Terminal, GitBranch, GitCommit, GitCompare, Rocket,
        Bug, Container, Workflow, Layout
    },
    'Infrastructure': {
        Server, Globe, Cloud, Shield, Lock, Unlock, Cpu, MemoryStick,
        Radio, Monitor
    },
    'Communication': {
        MessageSquare, Users
    },
    'Navigation & UI': {
        Home, Star, Sun, Moon, Palette, Play, Square, Calendar, Clock,
        LogOut, SettingsIcon, Newspaper, TrendingUp, BarChart3, Minus
    },
    'Brands': {
        Github
    }
};

const IconReferenceTab = () => {
    const [searchQuery, setSearchQuery] = useState('');
    const [copiedIcon, setCopiedIcon] = useState(null);

    async function handleCopyImport(name) {
        if (!await copyToClipboard(name)) return;
        setCopiedIcon(name);
        setTimeout(() => setCopiedIcon(null), 1500);
    }

    const filteredCatalog = Object.entries(ICON_CATALOG).reduce((acc, [group, icons]) => {
        if (!searchQuery) {
            acc[group] = icons;
            return acc;
        }
        const filtered = Object.entries(icons).filter(([name]) =>
            name.toLowerCase().includes(searchQuery.toLowerCase())
        );
        if (filtered.length > 0) {
            acc[group] = Object.fromEntries(filtered);
        }
        return acc;
    }, {});

    const totalIcons = Object.values(ICON_CATALOG).reduce((sum, icons) => sum + Object.keys(icons).length, 0);

    return (
        <div className="settings-section">
            <h2>Icon Reference</h2>
            <p className="section-description">
                Lucide React icons available in the project ({totalIcons} icons). Click an icon name to copy it.
            </p>

            <div className="settings-card">
                <div className="form-group">
                    <div className="search-input-wrapper" style={{ position: 'relative' }}>
                        <Search size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', opacity: 0.5 }} />
                        <Input
                            type="text"
                            placeholder="Search icons..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            style={{ paddingLeft: 36 }}
                        />
                    </div>
                </div>
            </div>

            {Object.entries(filteredCatalog).map(([group, icons]) => (
                <div key={group} className="settings-card">
                    <h3>{group}</h3>
                    <div className="icon-reference-grid">
                        {Object.entries(icons).map(([name, IconComp]) => (
                            <button type="button"
                                key={name}
                                className={`icon-reference-item ${copiedIcon === name ? 'copied' : ''}`}
                                onClick={() => handleCopyImport(name)}
                                title={`Click to copy "${name}"`}
                            >
                                <IconComp size={20} />
                                <span className="icon-reference-name">
                                    {copiedIcon === name ? 'Copied!' : name}
                                </span>
                            </button>
                        ))}
                    </div>
                </div>
            ))}

            {Object.keys(filteredCatalog).length === 0 && (
                <div className="settings-card">
                    <p style={{ textAlign: 'center', opacity: 0.5 }}>No icons match &quot;{searchQuery}&quot;</p>
                </div>
            )}
        </div>
    );
};

export default IconReferenceTab;
