import api from "@/lib/api"

export interface CashFlowItem {
  id: string
  name: string | null
  code?: string | null
  parent?: string
  include_in_budget?: boolean | null
  created_at: string
  updated_at: string
  deleted: boolean
}

export interface CashFlowItemHierarchy extends CashFlowItem {
  children?: CashFlowItemHierarchy[]
}

export const CashFlowItemService = {
  getCashFlowItems: async () => {
    const { data } = await api.get<any[]>("/cash-flow-items/")
    return data.map((i) => ({
      id: i.id,
      name: i.name ?? null,
      code: i.code ?? null,
      parent: i.parent ?? undefined,
      include_in_budget: i.include_in_budget ?? null,
      created_at: i.created_at,
      updated_at: i.updated_at,
      deleted: !!i.deleted,
    })) as CashFlowItem[]
  },

  getCashFlowItem: async (id: string) => {
    const { data: i } = await api.get<any>(`/cash-flow-items/${id}/`)
    const mapped: CashFlowItem = {
      id: i.id,
      name: i.name ?? null,
      code: i.code ?? null,
      parent: i.parent ?? undefined,
      include_in_budget: i.include_in_budget ?? null,
      created_at: i.created_at,
      updated_at: i.updated_at,
      deleted: !!i.deleted,
    }
    return mapped
  },

  createCashFlowItem: async (data: Partial<CashFlowItem>) => {
    const payload = {
      name: data.name,
      parent: data.parent,
      include_in_budget: data.include_in_budget,
    }
    const response = await api.post<any>("/cash-flow-items/", payload)
    return CashFlowItemService.getCashFlowItem(response.data.id)
  },

  updateCashFlowItem: async (id: string, data: Partial<CashFlowItem>) => {
    const payload = {
      name: data.name,
      parent: data.parent,
      include_in_budget: data.include_in_budget,
    }
    await api.patch<any>(`/cash-flow-items/${id}/`, payload)
    return CashFlowItemService.getCashFlowItem(id)
  },

  deleteCashFlowItem: async (id: string) => {
    await api.delete(`/cash-flow-items/${id}/`)
  },

  getCashFlowItemHierarchy: async () => {
    const response = await api.get<any>("/cash-flow-items/hierarchy/")
    const normalize = (raw: any): CashFlowItemHierarchy => ({
      id: raw.id,
      name: raw.name ?? "—",
      code: raw.code ?? null,
      parent: raw.parent ?? undefined,
      include_in_budget: raw.include_in_budget ?? null,
      created_at: raw.created_at,
      updated_at: raw.updated_at,
      deleted: !!raw.deleted,
      children: Array.isArray(raw.children) ? raw.children.map(normalize) : undefined,
    })

    const data = response.data
    const rootArray: any[] = Array.isArray(data)
      ? data
      : Array.isArray(data?.items)
        ? data.items
        : Array.isArray(data?.children)
          ? data.children
        : Array.isArray(data?.results)
          ? data.results
          : data
            ? [data]
            : []

    const mapped = rootArray.map(normalize)

    // If backend returned a flat list (no children anywhere), build tree manually
    const hasAnyChildren = mapped.some((n) => Array.isArray(n.children) && n.children.length > 0)
    if (!hasAnyChildren) {
      const nodeMap = new Map<string, CashFlowItemHierarchy>()
      const roots: CashFlowItemHierarchy[] = []
      // Initialize nodes without children
      for (const r of rootArray) {
        const node: CashFlowItemHierarchy = {
          id: r.id,
          name: r.name ?? "—",
          code: r.code ?? null,
          parent: r.parent ?? undefined,
          include_in_budget: r.include_in_budget ?? null,
          created_at: r.created_at,
          updated_at: r.updated_at,
          deleted: !!r.deleted,
          children: [],
        }
        nodeMap.set(node.id, node)
      }
      // Link children to parents
      for (const node of Array.from(nodeMap.values())) {
        if (node.parent) {
          const parent = nodeMap.get(node.parent)
          if (parent) {
            (parent.children ||= []).push(node)
          } else {
            roots.push(node) // parent absent in list
          }
        } else {
          roots.push(node)
        }
      }
      return roots
    }

    return mapped
  }
}
