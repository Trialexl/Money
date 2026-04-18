"use client"

import { useQuery } from "@tanstack/react-query"

interface UseOptionalEntityQueryOptions<TData> {
  id: string | null | undefined
  queryKeyFactory: (id: string) => readonly unknown[]
  queryFn: (id: string) => Promise<TData>
  refetchOnMount?: boolean | "always"
  staleTime?: number
}

function useOptionalEntityQuery<TData>({
  id,
  queryKeyFactory,
  queryFn,
  refetchOnMount,
  staleTime,
}: UseOptionalEntityQueryOptions<TData>) {
  return useQuery({
    queryKey: id ? queryKeyFactory(id) : ["entity", "idle"],
    enabled: Boolean(id),
    queryFn: () => queryFn(id as string),
    refetchOnMount,
    staleTime,
  })
}

export function useEntityDetailQuery<TData>(options: UseOptionalEntityQueryOptions<TData>) {
  return useOptionalEntityQuery({
    ...options,
    refetchOnMount: "always",
    staleTime: 0,
  })
}

export function useEntityDuplicateQuery<TData>(options: UseOptionalEntityQueryOptions<TData>) {
  return useOptionalEntityQuery({
    ...options,
    refetchOnMount: "always",
    staleTime: 0,
  })
}
