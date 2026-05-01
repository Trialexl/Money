"use client"

import * as Popover from "@radix-ui/react-popover"
import { Check, ChevronsUpDown, Search } from "lucide-react"
import { useMemo, useState } from "react"

import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

export interface SearchableSelectOption {
  value: string
  label: string
  description?: string
  keywords?: string[]
}

export interface SearchableSelectGroup {
  label?: string
  options: SearchableSelectOption[]
}

interface SearchableSelectProps {
  id?: string
  value: string
  onValueChange: (value: string) => void
  options?: SearchableSelectOption[]
  groups?: SearchableSelectGroup[]
  placeholder: string
  searchPlaceholder?: string
  emptyLabel?: string
  disabled?: boolean
  className?: string
  triggerClassName?: string
}

function normalizeSearch(value: string) {
  return value.trim().toLocaleLowerCase("ru")
}

function optionMatches(option: SearchableSelectOption, query: string) {
  if (!query) {
    return true
  }

  return [option.label, option.description, ...(option.keywords ?? [])]
    .filter(Boolean)
    .some((value) => normalizeSearch(String(value)).includes(query))
}

export function SearchableSelect({
  id,
  value,
  onValueChange,
  options,
  groups,
  placeholder,
  searchPlaceholder = "Найти...",
  emptyLabel = "Ничего не найдено",
  disabled = false,
  className,
  triggerClassName,
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const normalizedGroups = useMemo<SearchableSelectGroup[]>(
    () => groups ?? [{ options: options ?? [] }],
    [groups, options]
  )
  const normalizedQuery = normalizeSearch(query)
  const flatOptions = useMemo(
    () => normalizedGroups.flatMap((group) => group.options),
    [normalizedGroups]
  )
  const selectedOption = flatOptions.find((option) => option.value === value)
  const visibleGroups = useMemo(
    () =>
      normalizedGroups
        .map((group) => ({
          ...group,
          options: group.options.filter((option) => optionMatches(option, normalizedQuery)),
        }))
        .filter((group) => group.options.length > 0),
    [normalizedGroups, normalizedQuery]
  )
  const firstVisibleOption = visibleGroups.find((group) => group.options.length > 0)?.options[0]

  const handleSelect = (nextValue: string) => {
    onValueChange(nextValue)
    setOpen(false)
    setQuery("")
  }

  return (
    <Popover.Root
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen)
        if (!nextOpen) {
          setQuery("")
        }
      }}
    >
      <Popover.Trigger asChild>
        <button
          id={id}
          type="button"
          role="combobox"
          aria-expanded={open}
          disabled={disabled}
          className={cn(
            "flex h-11 w-full items-center justify-between gap-2 rounded-xl border border-input bg-background/80 px-3 py-2 text-left text-sm text-foreground shadow-sm outline-none transition duration-200 hover:border-primary/30 focus:border-primary/35 focus:ring-4 focus:ring-primary/10 disabled:cursor-not-allowed disabled:opacity-50",
            triggerClassName,
            className
          )}
        >
          <span className={cn("truncate", !selectedOption && "text-muted-foreground")}>
            {selectedOption?.label || placeholder}
          </span>
          <ChevronsUpDown className="h-4 w-4 shrink-0 text-muted-foreground" />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={6}
          className="z-50 w-[var(--radix-popover-trigger-width)] overflow-hidden rounded-2xl border border-border/80 bg-popover text-popover-foreground shadow-xl"
        >
          <div className="border-b border-border/70 p-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && firstVisibleOption) {
                    event.preventDefault()
                    handleSelect(firstVisibleOption.value)
                  }

                  if (event.key === "Escape") {
                    event.preventDefault()
                    setOpen(false)
                  }
                }}
                placeholder={searchPlaceholder}
                className="h-10 rounded-xl bg-background/80 pl-9"
                autoFocus
              />
            </div>
          </div>

          <div className="max-h-72 overflow-y-auto p-1">
            {visibleGroups.length > 0 ? (
              visibleGroups.map((group, groupIndex) => (
                <div key={group.label ?? `group-${groupIndex}`} className="py-1">
                  {group.label ? (
                    <div className="px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                      {group.label}
                    </div>
                  ) : null}
                  {group.options.map((option) => {
                    const isSelected = option.value === value

                    return (
                      <button
                        key={option.value}
                        type="button"
                        role="option"
                        aria-selected={isSelected}
                        onClick={() => handleSelect(option.value)}
                        className={cn(
                          "flex w-full items-start gap-2 rounded-xl px-3 py-2 text-left text-sm transition hover:bg-accent hover:text-accent-foreground",
                          isSelected && "bg-accent/70 text-accent-foreground"
                        )}
                      >
                        <Check className={cn("mt-0.5 h-4 w-4 shrink-0", isSelected ? "opacity-100" : "opacity-0")} />
                        <span className="min-w-0">
                          <span className="block truncate font-medium">{option.label}</span>
                          {option.description ? (
                            <span className="mt-0.5 block truncate text-xs text-muted-foreground">{option.description}</span>
                          ) : null}
                        </span>
                      </button>
                    )
                  })}
                </div>
              ))
            ) : (
              <div className="px-3 py-6 text-center text-sm text-muted-foreground">{emptyLabel}</div>
            )}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
