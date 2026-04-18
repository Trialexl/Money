import { UserProfile } from "@/services/auth-service"

export function getUserDisplayName(user?: UserProfile | null) {
  if (!user) {
    return "FrontMoney"
  }

  return user.full_name?.trim() || user.username || "FrontMoney"
}

export function getUserShortName(user?: UserProfile | null) {
  if (!user) {
    return "FrontMoney"
  }

  const fullName = user.full_name?.trim()
  if (fullName) {
    return fullName.split(/\s+/)[0]
  }

  return user.username || "FrontMoney"
}

export function getUserStatusLabel(user?: UserProfile | null) {
  if (!user) {
    return null
  }

  if (user.status === "COMP") {
    return "Компания"
  }

  if (user.status === "PRIV") {
    return "Частное лицо"
  }

  return null
}

export function getUserSecondaryText(user?: UserProfile | null) {
  if (!user) {
    return "Авторизованный пользователь"
  }

  return getUserStatusLabel(user) || "Авторизованный пользователь"
}
