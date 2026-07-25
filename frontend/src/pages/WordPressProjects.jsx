import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ExternalLink, Plus, GitBranch, Layers } from 'lucide-react';
import wordpressApi from '../services/wordpress';
import { useToast } from '../contexts/ToastContext';
import EmptyState from '../components/EmptyState';
import { Badge } from '@/components/ui/badge';

const WordPressProjects = () => {
    const [projects, setProjects] = useState([]);
    const [loading, setLoading] = useState(true);
    const navigate = useNavigate();
    const toast = useToast();

    useEffect(() => {
        loadProjects();
    }, []);

    async function loadProjects() {
        setLoading(true);
        try {
            const data = await wordpressApi.getPipelines();
            setProjects(data.projects || []);
        } catch (err) {
            console.error('Failed to load projects:', err);
            toast.error('Failed to load WordPress projects');
        } finally {
            setLoading(false);
        }
    }

    if (loading) {
        return <EmptyState loading loadingVariant="cards" size="lg" title="Loading WordPress pipelines" />;
    }

    return (
        <div className="sk-tabgroup__inner wp-projects-page">
            {projects.length === 0 ? (
                <EmptyState
                    size="lg"
                    icon={Layers}
                    title="No WordPress Pipelines"
                    description="WordPress sites with environment pipelines appear here. Create a WordPress site with environments enabled to get started."
                />
            ) : (
                <div className="wp-projects-grid">
                    {projects.map(project => (
                        <ProjectCard
                            key={project.id}
                            project={project}
                            onClick={() => navigate(`/wordpress/pipelines/${project.id}`)}
                        />
                    ))}
                </div>
            )}
        </div>
    );
};

const ProjectCard = ({ project, onClick }) => {
    const isRunning = project.status === 'running';
    const envCount = project.environment_count || 0;
    const envTypes = project.environment_types || [];
    const domain = project.application?.domains?.[0] || project.url || '';

    return (
        <div className="wp-project-card" onClick={onClick}>
            <div className="wp-project-card-header">
                <div className="wp-site-icon">
                    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                        <path d="M12 2C6.486 2 2 6.486 2 12s4.486 10 10 10 10-4.486 10-10S17.514 2 12 2zm0 19.542c-5.261 0-9.542-4.281-9.542-9.542S6.739 2.458 12 2.458 21.542 6.739 21.542 12 17.261 21.542 12 21.542z" />
                    </svg>
                </div>
                <div className="wp-project-info">
                    <h3 className="wp-project-name">{project.name}</h3>
                    {domain && (
                        <span className="wp-project-domain">{domain}</span>
                    )}
                </div>
                <span className={`wp-env-status ${isRunning ? 'running' : 'stopped'}`}>
                    <span className="status-dot" />
                    {isRunning ? 'Running' : 'Stopped'}
                </span>
            </div>

            <div className="wp-project-card-body">
                <div className="wp-project-meta">
                    <div className="wp-project-meta-item">
                        <Layers size={14} />
                        <span>{envCount + 1} environment{envCount !== 0 ? 's' : ''}</span>
                    </div>
                    {envTypes.length > 0 && (
                        <div className="wp-project-env-badges">
                            <Badge variant="default">PROD</Badge>
                            {envTypes.includes('staging') && (
                                <Badge variant="secondary">STG</Badge>
                            )}
                            {envTypes.includes('development') && (
                                <Badge variant="outline">DEV</Badge>
                            )}
                            {envTypes.includes('multidev') && (
                                <Badge variant="secondary">MD</Badge>
                            )}
                        </div>
                    )}
                    {project.wp_version && (
                        <div className="wp-project-meta-item">
                            <span>WordPress {project.wp_version}</span>
                        </div>
                    )}
                    {project.git_repo_url && (
                        <div className="wp-project-meta-item">
                            <GitBranch size={14} />
                            <span>Git connected</span>
                        </div>
                    )}
                </div>
            </div>

            <div className="wp-project-card-footer">
                <span className="wp-project-card-cta">View Pipeline</span>
                <ExternalLink size={14} />
            </div>
        </div>
    );
};

export default WordPressProjects;
