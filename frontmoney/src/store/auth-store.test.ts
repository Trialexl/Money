import { beforeEach, describe, expect, it, vi } from "vitest"

const { authServiceMock, clearAuthTokensMock, isAuthenticatedMock } = vi.hoisted(() => ({
  authServiceMock: {
    login: vi.fn(),
    logout: vi.fn(),
    getProfile: vi.fn(),
  },
  clearAuthTokensMock: vi.fn(),
  isAuthenticatedMock: vi.fn(),
}))

vi.mock("@/services/auth-service", () => ({
  AuthService: authServiceMock,
}))

vi.mock("@/lib/auth", () => ({
  isAuthenticated: isAuthenticatedMock,
  clearAuthTokens: clearAuthTokensMock,
}))

import { useAuthStore } from "@/store/auth-store"

describe("useAuthStore", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    isAuthenticatedMock.mockReturnValue(false)
    useAuthStore.setState({
      isAuthenticated: false,
      isLoading: false,
      user: null,
      error: null,
    })
  })

  it("logs in and stores the loaded profile", async () => {
    authServiceMock.login.mockResolvedValue(undefined)
    authServiceMock.getProfile.mockResolvedValue({
      id: "user-1",
      username: "admin",
      full_name: "Admin User",
    })

    await useAuthStore.getState().login("admin", "secret")

    expect(authServiceMock.login).toHaveBeenCalledWith({ username: "admin", password: "secret" })
    expect(authServiceMock.getProfile).toHaveBeenCalledTimes(1)
    expect(useAuthStore.getState().isAuthenticated).toBe(true)
    expect(useAuthStore.getState().user).toMatchObject({
      id: "user-1",
      username: "admin",
    })
    expect(useAuthStore.getState().error).toBeNull()
  })

  it("clears tokens and state on logout", async () => {
    useAuthStore.setState({
      isAuthenticated: true,
      isLoading: false,
      user: { id: "user-1", username: "admin" },
      error: null,
    })
    authServiceMock.logout.mockResolvedValue(undefined)

    await useAuthStore.getState().logout()

    expect(authServiceMock.logout).toHaveBeenCalledTimes(1)
    expect(clearAuthTokensMock).toHaveBeenCalledTimes(1)
    expect(useAuthStore.getState().isAuthenticated).toBe(false)
    expect(useAuthStore.getState().user).toBeNull()
  })

  it("drops the session when profile loading returns 401", async () => {
    isAuthenticatedMock.mockReturnValue(true)
    useAuthStore.setState({
      isAuthenticated: true,
      isLoading: false,
      user: { id: "user-1", username: "admin" },
      error: null,
    })
    authServiceMock.getProfile.mockRejectedValue({
      response: { status: 401 },
    })

    await useAuthStore.getState().loadProfile()

    expect(authServiceMock.getProfile).toHaveBeenCalledTimes(1)
    expect(clearAuthTokensMock).toHaveBeenCalledTimes(1)
    expect(useAuthStore.getState().isAuthenticated).toBe(false)
    expect(useAuthStore.getState().user).toBeNull()
  })
})
