import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { cn } from '@/lib/utils';

// Right-side slide-over, built on the existing shadcn Sheet (Radix dialog) so
// focus-trap / escape / overlay behavior is consistent. Renders the redesign's
// drawer-head chrome (icon chip + title + mono subtitle). Use this as the one
// shared drawer pattern instead of the per-feature drawers.
//
//   <Drawer open={open} onOpenChange={setOpen} title="wp-config.php"
//           subtitle="server filesystem" icon={<FileIcon/>} width={760}>
//       …body…
//   </Drawer>
//
// NOTE: `.sk-drawer__body` is the scroll region and carries NO padding — some
// drawers (log tails, tables, editors) run their content edge-to-edge. Ordinary
// form/detail bodies must pad themselves, or every field sits flush against the
// panel edge. Pad the body's own root class, not `.sk-drawer__body`.
export function Drawer({
    open,
    onOpenChange,
    title,
    subtitle,
    icon,
    iconColor,
    width = 720,
    side = 'right',
    headerExtra,
    className,
    children,
}) {
    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent side={side} className={cn('sk-drawer', className)} style={{ width, maxWidth: '95vw' }}>
                <div className="sk-drawer__head">
                    {icon && (
                        <span className="sk-drawer__ico" style={iconColor ? { color: iconColor } : undefined}>
                            {icon}
                        </span>
                    )}
                    <div style={{ flex: 1, minWidth: 0 }}>
                        {/* SheetTitle is required by Radix for a11y; keep it as the visible title. */}
                        <SheetTitle className="sk-drawer__title">{title}</SheetTitle>
                        {subtitle && <div className="sk-drawer__sub">{subtitle}</div>}
                    </div>
                    {headerExtra}
                </div>
                <div className="sk-drawer__body">{children}</div>
            </SheetContent>
        </Sheet>
    );
}

export default Drawer;
