'use client'

import { useEffect } from 'react'
import Link from 'next/link'

export default function HomePage() {
  useEffect(() => {
    window.location.replace('/dashboard')
  }, [])

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-6 text-foreground">
      <div className="max-w-md text-center">
        <h1 className="text-2xl font-semibold">Перенаправление...</h1>
        <p className="mt-3 text-sm text-muted-foreground">
          Если переход не сработал автоматически, откройте{' '}
          <Link href="/dashboard" className="font-medium text-primary underline-offset-4 hover:underline">
            рабочий стол
          </Link>
          .
        </p>
      </div>
    </main>
  )
}
