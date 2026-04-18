import api from "@/lib/api"

export interface Project {
  id: string
  name: string
  code?: string | null
  created_at: string
  updated_at: string
  deleted: boolean
}

export const ProjectService = {
  getProjects: async (isActive?: boolean) => {
    // API не поддерживает is_active; возвращаем список как есть
    const { data } = await api.get<any[]>("/projects/")
    return data.map((p) => ({
      id: p.id,
      name: p.name,
      code: p.code ?? null,
      created_at: p.created_at,
      updated_at: p.updated_at,
      deleted: !!p.deleted,
    })) as Project[]
  },

  getProject: async (id: string) => {
    const { data: p } = await api.get<any>(`/projects/${id}/`)
    const mapped: Project = {
      id: p.id,
      name: p.name,
      code: p.code ?? null,
      created_at: p.created_at,
      updated_at: p.updated_at,
      deleted: !!p.deleted,
    }
    return mapped
  },

  createProject: async (data: Partial<Project>) => {
    const payload = { name: data.name }
    const response = await api.post<any>("/projects/", payload)
    return ProjectService.getProject(response.data.id)
  },

  updateProject: async (id: string, data: Partial<Project>) => {
    const payload = { name: data.name }
    await api.patch<any>(`/projects/${id}/`, payload)
    return ProjectService.getProject(id)
  },

  deleteProject: async (id: string) => {
    await api.delete(`/projects/${id}/`)
  }
}
