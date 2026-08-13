import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cn } from '@/lib/utils';

// Map shadcn-style `variant` prop to our SCSS .btn-* classes.
// SCSS owns all geometry, color and hover state — see styles/components/_buttons.scss
const VARIANT_CLASS = {
  default:     'btn-primary',
  primary:     'btn-primary',
  destructive: 'btn-danger',
  danger:      'btn-danger',
  outline:     'btn-secondary',
  secondary:   'btn-soft',
  ghost:       'btn-ghost',
  link:        'btn-link',
};

const SIZE_CLASS = {
  default: '',
  md:      '',
  sm:      'btn-sm',
  lg:      'btn-lg',
  icon:    'btn-icon',
};

function buttonVariants({ variant = 'default', size = 'default', className } = {}) {
  return cn(
    'btn',
    VARIANT_CLASS[variant] ?? VARIANT_CLASS.default,
    SIZE_CLASS[size] ?? '',
    className,
  );
}

// forwardRef is load-bearing, not ceremony: every Radix trigger used as
// `<PopoverTrigger asChild><Button/></PopoverTrigger>` hands the button a ref
// and uses that element as the popper's anchor. Without it React drops the ref
// ("Function components cannot be given refs … Primitive.button.SlotClone"),
// floating-ui never gets a reference element, and the panel is left parked at
// its pre-position `translate(0, -200%)` — open, focusable and completely
// off-screen. That is why Sort/Columns/Views/Filter looked like dead buttons.
const Button = React.forwardRef(({ className, variant, size, asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot : 'button';
  return (
    <Comp
      ref={ref}
      data-slot="button"
      className={buttonVariants({ variant, size, className })}
      {...props}
    />
  );
});
Button.displayName = 'Button';

export { Button, buttonVariants };

