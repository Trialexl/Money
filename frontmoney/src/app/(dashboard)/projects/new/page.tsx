"use client"

import Link from "next/link"
import { Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { FolderKanban } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import ProjectForm from "@/components/shared/project-form"
import { useEntityDuplicateQuery } from "@/hooks/use-entity-query"
import { queryKeys } from "@/lib/query-keys"
import { Button } from "@/components/ui/button"
import { ProjectService } from "@/services/project-service"

function Inner() {
  const searchParams = useSearchParams()
  const duplicateId = searchParams.get("duplicate")

  const duplicateQuery = useEntityDuplicateQuery({
    id: duplicateId,
    queryKeyFactory: queryKeys.projects.duplicate,
    queryFn: ProjectService.getProject,
  })

  if (duplicateId && (duplicateQuery.isLoading || duplicateQuery.isFetching)) {
    return <FullPageLoader label="Подготавливаем дубликат проекта..." />
  }

  if (duplicateId && duplicateQuery.isError) {
    return (
      <EmptyState
        icon={FolderKanban}
        title="Не удалось загрузить проект для дублирования"
        description="Исходный проект не загрузился. Можно вернуться к каталогу или создать проект с нуля."
        action={
          <Button asChild>
            <Link href="/projects">К проектам</Link>
          </Button>
        }
      />
    )
  }

  return <ProjectForm project={duplicateQuery.data || undefined} />
}

export default function NewProjectPage() {
  return (
    <Suspense fallback={<FullPageLoader label="Готовим форму проекта..." />}>
      <Inner />
    </Suspense>
  )
}
