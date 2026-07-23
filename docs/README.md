# Документация Money

Корневая папка `docs/` является единой точкой входа в документацию объединенного проекта.

Новые продуктовые и архитектурные документы нужно добавлять сюда. Исторические документы frontend и backend пока остаются в своих папках, чтобы не ломать существующие ссылки и рабочий контекст, но индексируются здесь.

## Агенты

- [Навыки агентов и настройка секретов](agent-skills.md)

## Продуктовые документы

- [PRD: финансовые инструменты](product/financial-instruments-prd.md)
- [Backlog: финансовые инструменты](product/financial-instruments-tasks.md)
- [Backlog: стабилизация приложения](product/application-stabilization-tasks.md)
- [Investment module](investment-module.md)

## Общая эксплуатация

- [Server runbook: установка, обновление, cron, backup](operations/server-runbook.md)
- [Корневой README](../README.md)
- [HTTPS и Docker deployment](../moneybackend/docs/docker_https_deploy.md)
- [1C sync contract](../moneybackend/docs/1c_extension_sync.md)
- [Паритет доменной модели с 1С](../moneybackend/docs/domain_parity.md)

## Backend

- [Backend README](../moneybackend/README.md)
- [Backend задачи](../moneybackend/task.md)
- [1C migration backlog](../moneybackend/1c_migration_backlog.md)
- [AI operations](../moneybackend/docs/ai_operations.md)
- [Frontend handoff](../moneybackend/docs/frontend_handoff.md)

## Frontend

- [Frontend README](../frontmoney/README.md)
- [Frontend orientation](../frontmoney/docs/project-orientation.md)
- [Backend contract для frontend](../frontmoney/docs/backend.md)
- [AI operations frontend](../frontmoney/docs/ai_operations.md)
- [Frontend handoff](../frontmoney/docs/frontend_handoff.md)
- [Frontend tasks](../frontmoney/tasks.md)

## Правило на будущее

- продуктовые PRD и решения по UX: `docs/product/`
- общие архитектурные решения: `docs/architecture/`
- эксплуатация и deployment: `docs/operations/`
- интеграции: `docs/integrations/`

Если документ относится только к реализации конкретного приложения и нужен рядом с кодом, он может оставаться внутри `frontmoney/` или `moneybackend/`, но ссылка на него должна быть добавлена в этот индекс.
