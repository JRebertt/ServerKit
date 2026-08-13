import { useMemo, useState } from 'react';
import { BookOpen, Search, ExternalLink, FileText } from 'lucide-react';
import { Input } from '@/components/ui/input';
import PageLayout from '../layouts/PageLayout';
import EmptyState from '../components/EmptyState';

const REPO_DOCS_URL = 'https://github.com/jhd3197/ServerKit/blob/main/docs';

const DOC_GROUPS = [
    {
        id: 'getting-started',
        title: 'Getting Started',
        docs: [
            { file: 'README.md', title: 'Docs Home', desc: 'Documentation index' },
            { file: 'INSTALLATION.md', title: 'Installation', desc: 'Install ServerKit on a server' },
            { file: 'LOCAL_DEVELOPMENT.md', title: 'Local Development', desc: 'Run the panel locally' },
            { file: 'DEPLOYMENT.md', title: 'Deployment', desc: 'Production deployment guide' },
        ],
    },
    {
        id: 'reference',
        title: 'Reference',
        docs: [
            { file: 'ARCHITECTURE.md', title: 'Architecture', desc: 'How ServerKit is structured' },
            { file: 'API.md', title: 'API Reference', desc: 'REST API documentation' },
            { file: 'MULTI_ENVIRONMENT.md', title: 'Multi-Environment', desc: 'Manage multiple environments' },
            { file: 'MCP_SERVER_ACCESS.md', title: 'MCP Server Access', desc: 'Model Context Protocol access' },
            { file: 'pairing.md', title: 'Pairing', desc: 'Pairing servers with the panel' },
            { file: 'PLAN_AGENT_FLEET.md', title: 'Agent Fleet Plan', desc: 'Multi-server agent design' },
        ],
    },
    {
        id: 'product',
        title: 'Product Notes',
        docs: [
            { file: 'FEATURE_GAPS.md', title: 'Feature Gaps', desc: 'Known gaps and limitations' },
            { file: 'COMPETITIVE_ANALYSIS.md', title: 'Competitive Analysis', desc: 'Market comparison' },
            { file: 'MARKET_POSITIONING.md', title: 'Market Positioning', desc: 'Product positioning notes' },
        ],
    },
    {
        id: 'translations',
        title: 'Translations',
        docs: [
            { file: 'README.es.md', title: 'README (Español)', desc: 'Spanish translation' },
            { file: 'README.pt.md', title: 'README (Português)', desc: 'Portuguese translation' },
            { file: 'README.zh-CN.md', title: 'README (简体中文)', desc: 'Simplified Chinese translation' },
        ],
    },
];

const ROOT_DOCS = [
    { file: 'README.md', title: 'Project README', desc: 'Top-level project overview', root: true },
    { file: 'CONTRIBUTING.md', title: 'Contributing', desc: 'How to contribute', root: true },
    { file: 'AGENTS.md', title: 'AGENTS.md', desc: 'Guidance for AI/agent contributors', root: true },
    { file: 'CLAUDE.md', title: 'CLAUDE.md', desc: 'Guidance for Claude Code', root: true },
    { file: 'ROADMAP.md', title: 'Roadmap', desc: 'Planned features', root: true },
    { file: 'SECURITY_AUDIT.md', title: 'Security Audit', desc: 'Security findings', root: true },
];

const REPO_ROOT_URL = 'https://github.com/jhd3197/ServerKit/blob/main';

export default function Documentation() {
    const [query, setQuery] = useState('');

    const matches = (s) => s.toLowerCase().includes(query.trim().toLowerCase());

    const groups = useMemo(() => {
        if (!query.trim()) return DOC_GROUPS;
        return DOC_GROUPS.map(g => ({
            ...g,
            docs: g.docs.filter(d => matches(d.title) || matches(d.file) || matches(d.desc)),
        })).filter(g => g.docs.length);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [query]);

    const rootDocs = useMemo(() => {
        if (!query.trim()) return ROOT_DOCS;
        return ROOT_DOCS.filter(d => matches(d.title) || matches(d.file) || matches(d.desc));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [query]);

    const empty = !groups.length && !rootDocs.length;

    return (
        <PageLayout
            className="documentation"
            icon={<BookOpen size={18} />}
            title="Documentation"
            meta={<>dev only</>}
            actions={(
                <div className="documentation__search">
                    <Search size={14} />
                    <Input
                        placeholder="Filter docs…"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                    />
                </div>
            )}
        >
            {empty && (
                <EmptyState icon={BookOpen} title={`No docs match “${query}”.`} />
            )}

            {!!rootDocs.length && (
                <section className="documentation__group">
                    <h3 className="documentation__group-title">Repository Root</h3>
                    <ul className="documentation__list">
                        {rootDocs.map(d => (
                            <DocItem key={d.file} doc={d} baseUrl={REPO_ROOT_URL} pathPrefix="" />
                        ))}
                    </ul>
                </section>
            )}

            {groups.map(g => (
                <section key={g.id} className="documentation__group">
                    <h3 className="documentation__group-title">{g.title}</h3>
                    <ul className="documentation__list">
                        {g.docs.map(d => (
                            <DocItem key={d.file} doc={d} baseUrl={REPO_DOCS_URL} pathPrefix="docs/" />
                        ))}
                    </ul>
                </section>
            ))}
        </PageLayout>
    );
}

function DocItem({ doc, baseUrl, pathPrefix }) {
    return (
        <li>
            <a
                href={`${baseUrl}/${doc.file}`}
                target="_blank"
                rel="noreferrer noopener"
                className="documentation__link"
            >
                <span className="documentation__icon">
                    <FileText size={14} />
                </span>
                <span className="documentation__label">{doc.title}</span>
                <span className="documentation__path">{pathPrefix}{doc.file}</span>
                <ExternalLink size={12} className="documentation__ext" />
            </a>
            {doc.desc && <span className="documentation__note">{doc.desc}</span>}
        </li>
    );
}
