import { useNavigate } from 'react-router-dom';
import {
    Plus, Boxes, Server, Activity, Globe, LayoutGrid, FolderKanban, Clock,
} from 'lucide-react';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';

// Global quick-create (the CRM "+" button). One entry point for every "new
// thing" flow, wherever you are. Route-based flows navigate directly; flows
// that live in a modal/drawer on a list page navigate with a
// `?focus=create:<kind>` deep link, which the destination page opens via
// useFocusParam.
const CREATE_ITEMS = [
    { kind: 'service', label: 'Service', icon: Boxes, path: '/services/new' },
    { kind: 'server', label: 'Server', icon: Server, path: '/servers?focus=create:server' },
    { kind: 'monitor', label: 'Monitor', icon: Activity, path: '/monitoring/monitors?focus=create:monitor' },
    { kind: 'domain', label: 'Domain', icon: Globe, path: '/domains?focus=create:domain' },
    { kind: 'cron', label: 'Cron job', icon: Clock, path: '/cron?focus=create:cron' },
    { kind: 'workspace', label: 'Workspace', icon: LayoutGrid, path: '/workspaces?focus=create:workspace' },
    { kind: 'project', label: 'Project', icon: FolderKanban, path: '/projects?focus=create:project' },
];

export function QuickCreate({ className, variant = 'icon' }) {
    const navigate = useNavigate();
    // 'icon' — compact square button (mobile top bar). 'sidebar' — small
    // circular accent FAB (AI chat-bubble style) that lives on the first
    // sidebar category row; its menu opens downward since the trigger sits at
    // the top of the nav.
    const fab = variant === 'sidebar';
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <button
                    type="button"
                    className={cn('quick-create', fab && 'quick-create--fab', className)}
                    title="Create new…"
                    aria-label="Create new"
                >
                    <Plus size={fab ? 13 : 16} />
                </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
                side={fab ? 'bottom' : 'top'}
                align="end"
                sideOffset={8}
            >
                {CREATE_ITEMS.map((item) => (
                    <DropdownMenuItem key={item.kind} onSelect={() => navigate(item.path)}>
                        <item.icon size={14} aria-hidden="true" />
                        New {item.label}
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    );
}

export default QuickCreate;
