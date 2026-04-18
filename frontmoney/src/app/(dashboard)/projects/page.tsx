"use client"

import Link from "next/link"
import { useDeferredValue, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Copy, FolderKanban, Layers3, PencilLine, Plus, Search, Trash2 } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import { PageHeader } from "@/components/shared/page-header"
import { StatCard } from "@/components/shared/stat-card"
import { useActiveProjectsQuery } from "@/hooks/use-reference-data"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { formatDate } from "@/lib/formatters"
import { ProjectService } from "@/services/project-service"

export default function ProjectsPage() {
  const queryClient = useQueryClient()
  const [searchTerm, setSearchTerm] = useState("")
  const deferredSearch = useDeferredValue(searchTerm)

  const projectsQuery = useActiveProjectsQuery()

  const deleteMutation = useMutation({
    mutationFn: (projectId: string) => ProjectService.deleteProject(projectId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["projects"] }),
  })

  if (projectsQuery.isLoading) {
    return <FullPageLoader label="Загружаем проекты..." />
  }

  if (projectsQuery.isError || !projectsQuery.data) {
    return (
      <EmptyState
        icon={FolderKanban}
        title="Не удалось загрузить проекты"
        description="Список проектов сейчас недоступен. Проверь backend API и попробуй снова."
        action={<Button onClick={() => projectsQuery.refetch()}>Повторить</Button>}
      />
    )
  }

  const projects = projectsQuery.data
  const filteredProjects = projects
    .filter((project) => {
      if (!deferredSearch.trim()) {
        return true
      }

      const haystack = `${project.name} ${project.code ?? ""}`.toLowerCase()
      return haystack.includes(deferredSearch.toLowerCase())
    })
    .sort((left, right) => left.name.localeCompare(right.name, "ru"))

  const recentProjects = projects.filter((project) => {
    const createdAt = new Date(project.created_at)
    const thirtyDaysAgo = new Date()
    thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30)
    return createdAt >= thirtyDaysAgo
  }).length

  const codedProjects = projects.filter((project) => Boolean(project.code)).length

  const handleDelete = async (projectId: string) => {
    if (!window.confirm("Удалить этот проект? На фронте это необратимо.")) {
      return
    }

    await deleteMutation.mutateAsync(projectId)
  }

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Reference data"
        title="Проекты"
        description="Проекты дают контекст операциям и бюджетам: клиент, направление, личная цель или рабочий трек. Новый UI делает их быстрым рабочим слоем, а не формальной справочкой."
      />

      <div className="grid gap-4 md:grid-cols-3">
        <StatCard label="Всего проектов" value={String(projects.length)} hint="Все доступные проектные контексты" icon={FolderKanban} variant="compact" />
        <StatCard label="Созданы за 30 дней" value={String(recentProjects)} hint="Новый слой активности" icon={Layers3} variant="compact" />
        <StatCard label="С внутренним кодом" value={String(codedProjects)} hint="Удобно для поиска и автоматизации" icon={Search} variant="compact" />
      </div>

      <Card>
        <CardContent className="p-6">
          <div className="space-y-2">
            <Label htmlFor="project-search">Поиск по проектам</Label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="project-search"
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                placeholder="Название, код или часть контекста"
                className="pl-11"
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {filteredProjects.length === 0 ? (
        <EmptyState
          icon={FolderKanban}
          title="Проекты не найдены"
          description="По текущему поиску ничего не найдено. Очисти поиск или создай новый проект."
          action={
            <Button asChild variant="outline">
              <Link href="/projects/new">Создать проект</Link>
            </Button>
          }
        />
      ) : (
        <div className="grid gap-5 xl:grid-cols-2">
          {filteredProjects.map((project) => (
            <Card key={project.id}>
              <CardContent className="p-6">
                <div className="flex items-start justify-between gap-4">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="text-2xl font-semibold tracking-[-0.04em]">{project.name}</h2>
                      <Badge variant="secondary">Project</Badge>
                      {project.code ? <Badge variant="outline">{project.code}</Badge> : null}
                    </div>
                    <p className="text-sm leading-6 text-muted-foreground">
                      Проектный контекст доступен для документов и аналитики. Из этого экрана его удобно поддерживать в чистом состоянии.
                    </p>
                  </div>
                  <div className="rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-primary">
                    {formatDate(project.created_at)}
                  </div>
                </div>

                <div className="mt-6 grid gap-3 rounded-[24px] border border-border/60 bg-background/70 p-4 text-sm text-muted-foreground sm:grid-cols-2">
                  <div>
                    <div className="text-xs uppercase tracking-[0.18em]">Создан</div>
                    <div className="mt-2 text-foreground">{formatDate(project.created_at)}</div>
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-[0.18em]">Обновлен</div>
                    <div className="mt-2 text-foreground">{formatDate(project.updated_at)}</div>
                  </div>
                </div>

                <div className="mt-6 flex flex-wrap gap-1">
                  <Button asChild variant="ghost" size="icon" aria-label="Редактировать" title="Редактировать">
                    <Link href={`/projects/${project.id}/edit`}>
                      <PencilLine className="h-4 w-4" />
                    </Link>
                  </Button>
                  <Button asChild variant="ghost" size="icon" aria-label="Дублировать" title="Дублировать">
                    <Link href={`/projects/new?duplicate=${project.id}`}>
                      <Copy className="h-4 w-4" />
                    </Link>
                  </Button>
                  <Button variant="ghost" size="icon" onClick={() => handleDelete(project.id)} disabled={deleteMutation.isPending} aria-label="Удалить" title="Удалить">
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
