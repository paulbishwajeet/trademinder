// frontend/src/components/ui/command.tsx — shadcn/ui Command over cmdk
import * as React from 'react'
import { Command as CommandPrimitive } from 'cmdk'
import { cn } from '../../lib/utils'

export function Command({ className, ...props }: React.ComponentProps<typeof CommandPrimitive>) {
  return <CommandPrimitive className={cn('flex flex-col text-sm text-gray-900', className)} {...props} />
}

export function CommandInput({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.Input>) {
  return <CommandPrimitive.Input className={cn('outline-none placeholder:text-gray-400', className)} {...props} />
}

export function CommandList({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.List>) {
  return <CommandPrimitive.List className={cn('max-h-64 overflow-y-auto p-1', className)} {...props} />
}

export function CommandEmpty({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.Empty>) {
  return <CommandPrimitive.Empty className={cn('px-2 py-2 text-xs text-gray-500', className)} {...props} />
}

export function CommandItem({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.Item>) {
  return (
    <CommandPrimitive.Item
      className={cn(
        'flex cursor-pointer select-none items-center justify-between gap-2 rounded px-2 py-1.5 text-sm outline-none',
        'data-[selected=true]:bg-gray-100',
        className,
      )}
      {...props}
    />
  )
}
