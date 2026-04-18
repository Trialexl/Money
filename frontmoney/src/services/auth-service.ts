import api from "@/lib/api"
import { setAuthTokens, clearAuthTokens, getRefreshToken } from "@/lib/auth"

interface LoginRequest {
  username: string
  password: string
}

interface LoginResponse {
  access: string
  refresh: string
}

export type ProfileStatus = "COMP" | "PRIV"

export interface UserProfile {
  id?: string
  username: string
  full_name?: string | null
  status?: ProfileStatus | string | null
  tax_id?: string | null
}

function normalizeProfile(raw: any): UserProfile {
  if (!raw) {
    return {
      username: "",
      full_name: null,
      status: null,
      tax_id: null,
    }
  }

  return {
    id: raw.id,
    username: raw.username ?? "",
    full_name: raw.full_name ?? null,
    status: raw.status ?? null,
    tax_id: raw.tax_id ?? null,
  }
}

export const AuthService = {
  login: async (data: LoginRequest) => {
    const response = await api.post<LoginResponse>("/auth/token/", data)
    setAuthTokens(response.data.access, response.data.refresh)
    return response.data
  },

  logout: async () => {
    const refresh = getRefreshToken()
    try {
      if (refresh) {
        await api.post("/auth/logout/", { refresh })
      }
    } catch (error) {
      console.error("Logout error:", error)
    } finally {
      clearAuthTokens()
    }
  },

  refreshToken: async (refreshToken: string) => {
    const response = await api.post<{ access: string }>("/auth/refresh/", { refresh: refreshToken })
    return response.data
  },

  getProfile: async () => {
    // API: GET /api/v1/profile/ возвращает массив профилей текущего пользователя
    const { data } = await api.get<UserProfile[] | UserProfile>("/profile/")
    const profile = Array.isArray(data) ? data[0] : data
    return normalizeProfile(profile)
  },

  updateProfile: async (data: Partial<UserProfile> & { id?: string }) => {
    if (!data.id) {
      const current = await AuthService.getProfile()
      data.id = current.id
    }

    if (!data.id) {
      throw new Error("Backend не вернул id профиля")
    }

    const payload = {
      username: data.username,
      full_name: data.full_name,
      status: data.status,
      tax_id: data.tax_id,
    }

    const response = await api.patch<UserProfile>(`/profile/${data.id}/`, payload)
    return normalizeProfile(response.data)
  }
}
