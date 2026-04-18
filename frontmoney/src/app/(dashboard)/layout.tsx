"use client"

import { useEffect, useState } from "react"
import { usePathname, useRouter } from "next/navigation"

import { AppShell } from "@/components/shared/app-shell"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import { isAuthenticated } from "@/lib/auth"
import { useAuthStore } from "@/store/auth-store"

export default function DashboardLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  const router = useRouter()
  const pathname = usePathname()
  const { loadProfile, isLoading } = useAuthStore()
  const [isReady, setIsReady] = useState(false)

  useEffect(() => {
    let cancelled = false

    const bootstrap = async () => {
      if (!isAuthenticated()) {
        router.replace("/auth/login")
        return
      }

      try {
        await loadProfile()
      } finally {
        if (!cancelled) {
          setIsReady(true)
        }
      }
    }

    bootstrap()

    return () => {
      cancelled = true
    }
  }, [loadProfile, router])

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/auth/login")
    }
  }, [pathname, router])

  if (!isReady || isLoading) {
    return <FullPageLoader />
  }

  return <AppShell>{children}</AppShell>
}
