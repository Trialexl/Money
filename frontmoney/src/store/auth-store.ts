"use client"

import { create } from "zustand"
import { AuthService, UserProfile } from "@/services/auth-service"
import { isAuthenticated, clearAuthTokens } from "@/lib/auth"

interface AuthState {
  isAuthenticated: boolean
  isLoading: boolean
  user: UserProfile | null
  error: string | null
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  loadProfile: () => Promise<void>
  setUser: (user: UserProfile | null) => void
}

export const useAuthStore = create<AuthState>((set) => ({
  isAuthenticated: isAuthenticated(),
  isLoading: false,
  user: null,
  error: null,
  
  login: async (username: string, password: string) => {
    set({ isLoading: true, error: null })
    try {
      await AuthService.login({ username, password })
      const user = await AuthService.getProfile()
      set({ isAuthenticated: true, user, isLoading: false })
    } catch (error: any) {
      set({ 
        error: error.response?.data?.detail || "Ошибка входа", 
        isLoading: false,
        isAuthenticated: false
      })
      throw error
    }
  },
  
  logout: async () => {
    set({ isLoading: true })
    try {
      await AuthService.logout()
    } finally {
      clearAuthTokens()
      set({ isAuthenticated: false, user: null, isLoading: false })
    }
  },
  
  loadProfile: async () => {
    if (!isAuthenticated()) {
      set({ isAuthenticated: false, user: null })
      return
    }
    
    set({ isLoading: true, error: null })
    try {
      const user = await AuthService.getProfile()
      set({ user, isAuthenticated: true, isLoading: false })
    } catch (error: any) {
      if (error.response?.status === 401) {
        clearAuthTokens()
        set({ isAuthenticated: false, user: null, isLoading: false })
      } else {
        set({ 
          error: "Failed to load profile", 
          isLoading: false,
          isAuthenticated: isAuthenticated()
        })
      }
    }
  },

  setUser: (user) => {
    set({ user, isAuthenticated: Boolean(user) || isAuthenticated() })
  },
}))
