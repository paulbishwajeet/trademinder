// frontend/src/components/ui/popover.tsx — shadcn/ui Popover over @radix-ui/react-popover
import * as React from 'react'
import * as PopoverPrimitive from '@radix-ui/react-popover'
import { cn } from '../../lib/utils'

export function Popover(props: React.ComponentProps<typeof PopoverPrimitive.Root>) {
  return <PopoverPrimitive.Root {...props} />
}

export function PopoverTrigger(props: React.ComponentProps<typeof PopoverPrimitive.Trigger>) {
  return <PopoverPrimitive.Trigger {...props} />
}

export function PopoverAnchor(props: React.ComponentProps<typeof PopoverPrimitive.Anchor>) {
  return <PopoverPrimitive.Anchor {...props} />
}

export function PopoverContent({
  className, align = 'start', sideOffset = 4, ...props
}: React.ComponentProps<typeof PopoverPrimitive.Content>) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        align={align}
        sideOffset={sideOffset}
        // An open popover owns Escape; page-level shortcuts check for this marker and stand down.
        data-escape-layer=""
        className={cn('z-50 rounded-md border border-gray-200 bg-white p-0 shadow-lg outline-none', className)}
        {...props}
      />
    </PopoverPrimitive.Portal>
  )
}
