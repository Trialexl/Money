import type { Metadata } from "next"

import { AppProviders } from "@/components/shared/app-providers"

import "./globals.css"

export const metadata: Metadata = {
  title: "FrontMoney",
  description: "Современный рабочий стол для управления личными финансами",
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="ru" className="scroll-smooth" suppressHydrationWarning>
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        <AppProviders>
          {children}
        </AppProviders>
      </body>
    </html>
  )
}
