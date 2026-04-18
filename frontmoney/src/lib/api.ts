import axios from "axios"
import { getAuthToken, clearAuthTokens } from "@/lib/auth"

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1"

const api = axios.create({
  baseURL: BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
})

// Request interceptor for adding auth token
api.interceptors.request.use(
  (config) => {
    const token = getAuthToken()
    if (token) {
      config.headers["Authorization"] = `Bearer ${token}`
    }
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
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true
      
      try {
        // Try to refresh token or redirect to login
        const refreshToken = localStorage.getItem("refreshToken")
        
        if (!refreshToken) {
          clearAuthTokens()
          window.location.href = "/auth/login"
          return Promise.reject(error)
        }
        
        const response = await axios.post(`${BASE_URL}/auth/refresh/`, {
          refresh: refreshToken,
        })
        
        if (response.data.access) {
          localStorage.setItem("authToken", response.data.access)
          
          // Retry original request with new token
          originalRequest.headers["Authorization"] = `Bearer ${response.data.access}`
          return axios(originalRequest)
        }
      } catch (refreshError) {
        clearAuthTokens()
        window.location.href = "/auth/login"
        return Promise.reject(refreshError)
      }
    }
    
    return Promise.reject(error)
  }
)

export default api
