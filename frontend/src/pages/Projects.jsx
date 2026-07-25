import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { FolderKanban, Plus, Layers, Boxes } from 'lucide-react';
import api from '../services/api';
import { useToast } from '../contexts/ToastContext';
import EmptyState from '../components/EmptyState';
import { useTopbarActions } from '@/hooks/useTopbarActions';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
} from '@/components/ui/dialog';

const Projects = () => {
    const [projects, setProjects] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showCreate, setShowCreate] = useState(false);
    const toast = useToast();

    const loadProjects = useCallback(async () => {
        setLoading(true);
        try {
            const data = await api.getProjects();
            setProjects(Array.isArray(data?.projects) ? data.projects : []);
        } catch (err) {
            console.error('Failed to load projects:', err);
            toast.error('Failed to load projects');
        } finally {
            setLoading(false);
        }
    }, [toast]);

    useEffect(() => {
        loadProjects();
    }, [loadProjects]);

    useTopbarActions(() => (
        <Button onClick={() => setShowCreate(true)}>
            <Plus size={16} /> New Project
        </Button>
    ), []);

    return (
        <div className="sk-tabgroup__inner projects-page">
            <div className="projects-page__body">
                {loading ? (
                    <EmptyState loading loadingVariant="cards" title="Loading projects" />
                ) : projects.length === 0 ? (
                    <EmptyState
                        icon={FolderKanban}
                        title="No projects yet"
                        description="Group your applications into projects and environments (production, staging, development) to keep things organized."
                        action={
                            <Button onClick={() => setShowCreate(true)}>
                                <Plus size={16} /> Create your first project
                            </Button>
                        }
                    />
                ) : (
                    <div className="projects-grid">
                        {projects.map(project => (
                            <ProjectCard key={project.id} project={project} />
                        ))}
                    </div>
                )}
            </div>

            <CreateProjectDialog
                open={showCreate}
                onOpenChange={setShowCreate}
                onCreated={() => {
                    setShowCreate(false);
                    loadProjects();
                }}
            />
        </div>
    );
};

const ProjectCard = ({ project }) => {
    const envCount = project.environment_count ?? 0;
    const appCount = project.app_count ?? 0;
    return (
        <Link to={`/projects/${project.id}`} className="project-card">
            <div className="project-card__header">
                <span className="project-card__icon" aria-hidden="true">
                    <FolderKanban size={18} />
                </span>
                <div className="project-card__titles">
                    <h3 className="project-card__name">{project.name}</h3>
                    <span className="project-card__slug">{project.slug}</span>
                </div>
            </div>
            {project.description && (
                <p className="project-card__description">{project.description}</p>
            )}
            <div className="project-card__stats">
                <span className="project-card__stat">
                    <Layers size={14} />
                    {envCount} environment{envCount === 1 ? '' : 's'}
                </span>
                <span className="project-card__stat">
                    <Boxes size={14} />
                    {appCount} app{appCount === 1 ? '' : 's'}
                </span>
            </div>
        </Link>
    );
};

const CreateProjectDialog = ({ open, onOpenChange, onCreated }) => {
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const toast = useToast();

    function reset() {
        setName('');
        setDescription('');
    }

    async function handleSubmit(e) {
        e.preventDefault();
        if (!name.trim()) {
            toast.error('Project name is required');
            return;
        }
        setSubmitting(true);
        try {
            await api.createProject({
                name: name.trim(),
                description: description.trim() || undefined,
            });
            toast.success('Project created');
            reset();
            onCreated();
        } catch (err) {
            toast.error(err.message || 'Failed to create project');
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <Dialog open={open} onOpenChange={(v) => { if (!v) reset(); onOpenChange(v); }}>
            <DialogContent>
                <form onSubmit={handleSubmit}>
                    <DialogHeader>
                        <DialogTitle>New Project</DialogTitle>
                        <DialogDescription>
                            A project groups your applications. It starts with a default
                            &quot;production&quot; environment you can rename or expand.
                        </DialogDescription>
                    </DialogHeader>

                    <div className="projects-form">
                        <div className="projects-form__field">
                            <Label htmlFor="project-name">Name</Label>
                            <Input
                                id="project-name"
                                value={name}
                                onChange={(e) => setName(e.target.value)}
                                placeholder="My Project"
                                autoFocus
                                required
                            />
                        </div>
                        <div className="projects-form__field">
                            <Label htmlFor="project-description">Description (optional)</Label>
                            <Textarea
                                id="project-description"
                                value={description}
                                onChange={(e) => setDescription(e.target.value)}
                                placeholder="What this project is for…"
                                rows={3}
                            />
                        </div>
                    </div>

                    <DialogFooter>
                        <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                            Cancel
                        </Button>
                        <Button type="submit" disabled={submitting || !name.trim()}>
                            {submitting ? 'Creating…' : 'Create Project'}
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
};

export default Projects;
