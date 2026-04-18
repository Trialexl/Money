"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { FolderKanban, Save } from "lucide-react"

import { PageHeader } from "@/components/shared/page-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Project, ProjectService } from "@/services/project-service"

interface ProjectFormProps {
  project?: Project
  isEdit?: boolean
}

export default function ProjectForm({ project, isEdit = false }: ProjectFormProps) {
  const router = useRouter()
  const queryClient = useQueryClient()
  const [name, setName] = useState(project?.name || "")

  useEffect(() => {
    setName(project?.name || "")
  }, [project])

  const projectMutation = useMutation({
    mutationFn: async () => {
      const payload: Partial<Project> = {
        name: name.trim(),
      }

      if (isEdit && project) {
        return ProjectService.updateProject(project.id, payload)
      }

      return ProjectService.createProject(payload)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["projects"] })
      router.push("/projects")
    },
  })

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await projectMutation.mutateAsync()
  }

  const errorMessage = projectMutation.error
    ? (projectMutation.error as any)?.response?.data?.detail || "Не удалось сохранить проект. Проверь данные и попробуй снова."
    : null

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Projects"
        title={isEdit ? "Редактирование проекта" : "Новый проект"}
        description={
          isEdit
            ? "Обнови название проекта. Этот слой нужен, чтобы операции и бюджеты имели понятный контекст."
            : "Создай проект как рабочий контейнер для направления, клиента, продукта или личной финансовой цели."
        }
        actions={
          <Button asChild variant="outline">
            <Link href="/projects">К списку</Link>
          </Button>
        }
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card>
          <CardHeader>
            <CardTitle>Основные параметры</CardTitle>
            <CardDescription>Проект должен быстро читаться в списках операций. Поэтому название важно сильнее описаний и декоративных полей.</CardDescription>
          </CardHeader>
          <CardContent>
            {errorMessage ? (
              <div className="mb-6 rounded-[24px] border border-destructive/20 bg-destructive/10 px-4 py-3 text-sm leading-6 text-destructive">
                {errorMessage}
              </div>
            ) : null}

            <form onSubmit={handleSubmit} className="space-y-6">
              <div className="space-y-2">
                <Label htmlFor="project-name">Название проекта</Label>
                <Input
                  id="project-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Например, Family budget 2026"
                  maxLength={25}
                  required
                />
              </div>

              <div className="flex flex-wrap gap-3">
                <Button type="submit" disabled={projectMutation.isPending || !name.trim()}>
                  <Save className="h-4 w-4" />
                  {projectMutation.isPending ? "Сохраняем..." : isEdit ? "Сохранить изменения" : "Создать проект"}
                </Button>
                <Button asChild variant="outline">
                  <Link href="/projects">Отмена</Link>
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Предпросмотр</CardTitle>
            <CardDescription>Так проект будет выглядеть в новом каталоге.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-[24px] border border-border/70 bg-background/70 p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-lg font-semibold tracking-[-0.03em]">{name.trim() || "Новый проект"}</div>
                  <div className="mt-1 text-sm text-muted-foreground">Контекст для операций, бюджетов и аналитики</div>
                </div>
                <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                  <FolderKanban className="h-5 w-5" />
                </div>
              </div>
              <div className="mt-5 flex flex-wrap gap-2">
                <Badge variant="secondary">Project</Badge>
                <Badge variant="outline">{project?.code ? `Код: ${project.code}` : "Код назначим автоматически"}</Badge>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
