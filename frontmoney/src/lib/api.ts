import axios from "axios"
import { clearAuthTokens } from "@/lib/auth"

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1"

const api = axios.create({
  baseURL: BASE_URL,
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
})

let refreshPromise: Promise<string> | null = null

function redirectToLogin() {
  if (typeof window === "undefined") {
    return
  }

  clearAuthTokens()

  if (window.location.pathname.startsWith("/auth/login")) {
    return
  }

  const returnTo = `${window.location.pathname}${window.location.search}${window.location.hash}`
  const params = new URLSearchParams()
  if (returnTo && returnTo !== "/") {
    params.set("return_to", returnTo)
  }

  const query = params.toString()
  window.location.assign(query ? `/auth/login?${query}` : "/auth/login")
}

async function refreshAccessToken() {
  if (refreshPromise) {
    return refreshPromise
  }

  refreshPromise = (async () => {
    const response = await axios.post(`${BASE_URL}/auth/refresh/`, {}, { withCredentials: true })

    return response.data?.access || "cookie-session"
  })().finally(() => {
    refreshPromise = null
  })

  return refreshPromise
}

api.interceptors.request.use(
  (config) => {
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor for handling errors
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    // Handle token expiration or authentication errors
    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      originalRequest._retry = true
      
      try {
        await refreshAccessToken()
        return api(originalRequest)
      } catch (refreshError) {
        redirectToLogin()
        return Promise.reject(refreshError)
      }
    }
    
    return Promise.reject(error)
  }
)

export default api
