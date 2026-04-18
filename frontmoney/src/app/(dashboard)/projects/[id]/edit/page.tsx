"use client"

import Link from "next/link"
import { useParams } from "next/navigation"
import { FolderKanban } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import ProjectForm from "@/components/shared/project-form"
import { useEntityDetailQuery } from "@/hooks/use-entity-query"
import { queryKeys } from "@/lib/query-keys"
import { Button } from "@/components/ui/button"
import { ProjectService } from "@/services/project-service"

export default function EditProjectPage() {
  const params = useParams()
  const idParam = Array.isArray((params as any)?.id) ? (params as any).id[0] : (params as any)?.id

  const projectQuery = useEntityDetailQuery({
    id: typeof idParam === "string" ? idParam : undefined,
    queryKeyFactory: queryKeys.projects.detail,
    queryFn: ProjectService.getProject,
  })

  if (projectQuery.isLoading || projectQuery.isFetching) {
    return <FullPageLoader label="Загружаем проект..." />
  }

  if (projectQuery.isError || !projectQuery.data) {
    return (
      <EmptyState
        icon={FolderKanban}
        title="Не удалось открыть проект"
        description="Проект не найден или backend не вернул его данные."
        action={
          <Button asChild>
            <Link href="/projects">К списку проектов</Link>
          </Button>
        }
      />
    )
  }

  return <ProjectForm project={projectQuery.data} isEdit />
}
