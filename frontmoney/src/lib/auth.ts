const SESSION_COOKIE_NAME = "money_session"

function hasSessionMarker(): boolean {
  if (typeof document === "undefined") {
    return false
  }
  return document.cookie.split(";").some((cookie) => cookie.trim().startsWith(`${SESSION_COOKIE_NAME}=`))
}

export const setAuthTokens = (_accessToken?: string, _refreshToken?: string) => {
  // Tokens are stored by the backend in HttpOnly cookies.
}

export const getAuthToken = (): string | null => null

export const getRefreshToken = (): string | null => null

export const clearAuthTokens = () => {
  if (typeof window !== "undefined") {
    localStorage.removeItem("authToken")
    localStorage.removeItem("refreshToken")
  }
  if (typeof document !== "undefined") {
    document.cookie = `${SESSION_COOKIE_NAME}=; Max-Age=0; path=/; SameSite=Lax`
  }
}

export const isAuthenticated = (): boolean => {
  return hasSessionMarker()
}
