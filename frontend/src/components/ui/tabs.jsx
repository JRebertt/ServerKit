import * as React from 'react';
import * as TabsPrimitive from '@radix-ui/react-tabs';
import { MoreHorizontal } from 'lucide-react';
import { Popover, PopoverTrigger, PopoverContent } from './popover';
import { cn } from '@/lib/utils';
import { useOverflowItems } from '@/hooks/useOverflowItems';
import { t } from '../../i18n/t';

const Tabs = TabsPrimitive.Root;

const TabsList = React.forwardRef(({ className, children, ...props }, ref) => {
  const childArray = React.Children.toArray(children).filter(React.isValidElement);
  const [popoverOpen, setPopoverOpen] = React.useState(false);
  const itemRefs = React.useRef([]);

  const getActiveIndex = React.useCallback(() => {
    let active = -1;
    itemRefs.current.forEach((el, i) => {
      if (el?.dataset?.state === 'active') active = i;
    });
    return active;
  }, []);

  const { containerRef, moreBtnRef, hiddenIndices, hiddenSet, recompute } = useOverflowItems({
    count: childArray.length,
    itemRefs,
    gap: 8,
    moreWidth: 36,
    getActiveIndex,
  });

  const setContainerRef = React.useCallback(
    (node) => {
      containerRef.current = node;
      if (typeof ref === 'function') ref(node);
      else if (ref) ref.current = node;
    },
    [ref, containerRef]
  );

  // Re-run when active tab changes (so active never stays hidden).
  React.useEffect(() => {
    if (typeof MutationObserver === 'undefined') return;
    const observers = itemRefs.current
      .map((el) => {
        if (!el) return null;
        const mo = new MutationObserver(() => recompute());
        mo.observe(el, { attributes: true, attributeFilter: ['data-state'] });
        return mo;
      })
      .filter(Boolean);
    return () => observers.forEach((o) => o.disconnect());
  }, [recompute, childArray.length]);

  return (
    <TabsPrimitive.List
      ref={setContainerRef}
      className={cn('tabs', className)}
      {...props}
    >
      {childArray.map((child, i) => {
        const isHidden = hiddenSet.has(i);
        return React.cloneElement(child, {
          key: child.key ?? i,
          ref: (el) => {
            itemRefs.current[i] = el;
          },
          style: {
            ...(child.props.style || {}),
            display: isHidden ? 'none' : child.props.style?.display,
          },
          'data-overflow': isHidden ? 'hidden' : undefined,
        });
      })}
      {hiddenIndices.length > 0 && (
        <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
          <PopoverTrigger asChild>
            <button
              ref={moreBtnRef}
              type="button"
              className="tab tabs-overflow-trigger"
              aria-label={t('app.tabs.moreTabs', 'More tabs')}
            >
              <MoreHorizontal size={16} />
            </button>
          </PopoverTrigger>
          <PopoverContent
            align="end"
            sideOffset={6}
            className="ui-popover-content"
          >
            <div className="tabs-overflow-list">
              {hiddenIndices.map((idx) => {
                const child = childArray[idx];
                if (!child) return null;
                const triggerEl = itemRefs.current[idx];
                const isActive = triggerEl?.dataset?.state === 'active';
                return (
                  <TabsPrimitive.Trigger
                    key={`overflow-${child.key ?? idx}`}
                    type="button"
                    value={child.props.value}
                    disabled={child.props.disabled}
                    className="tabs-overflow-item"
                    data-state={isActive ? 'active' : 'inactive'}
                    onClick={(event) => {
                      child.props.onClick?.(event);
                      setPopoverOpen(false);
                    }}
                  >
                    {child.props.children}
                  </TabsPrimitive.Trigger>
                );
              })}
            </div>
          </PopoverContent>
        </Popover>
      )}
    </TabsPrimitive.List>
  );
});
TabsList.displayName = TabsPrimitive.List.displayName;

const TabsTrigger = React.forwardRef(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn('tab', className)}
    {...props}
  />
));
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;

const TabsContent = React.forwardRef(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn('tab-content-pane', className)}
    {...props}
  />
));
TabsContent.displayName = TabsPrimitive.Content.displayName;

export { Tabs, TabsList, TabsTrigger, TabsContent };
