from django.core.management.base import BaseCommand, CommandError

from ops.models import ScheduledJobRun
from ops.scheduler import ensure_scheduled_jobs, get_job_definitions, run_due_jobs


class Command(BaseCommand):
    help = 'Запустить due регламентные задания из backend job registry.'

    def add_arguments(self, parser):
        parser.add_argument('--job', help='Ключ конкретного задания. Запускается принудительно.')
        parser.add_argument('--force', action='store_true', help='Запустить все включенные задания независимо от next_run_at.')
        parser.add_argument('--dry-run', action='store_true', help='Показать задания, которые были бы запущены.')
        parser.add_argument('--list', action='store_true', help='Синхронизировать registry и показать задания.')

    def handle(self, *args, **options):
        states = ensure_scheduled_jobs()

        if options['list']:
            for state in states:
                self.stdout.write(
                    f'{state.job_key}\t'
                    f'enabled={state.enabled}\t'
                    f'status={state.last_status}\t'
                    f'next={state.next_run_at}\t'
                    f'title={state.title}'
                )
            return

        try:
            runs = run_due_jobs(
                force=options['force'],
                job_key=options.get('job'),
                dry_run=options['dry_run'],
                triggered_by=ScheduledJobRun.TRIGGER_MANUAL if options.get('job') or options['force'] else ScheduledJobRun.TRIGGER_SCHEDULER,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        if options['dry_run']:
            if not runs:
                self.stdout.write('No jobs due.')
            for item in runs:
                self.stdout.write(
                    f'{item["job_key"]}\t'
                    f'due={item["due"]}\t'
                    f'next={item["next_run_at"]}\t'
                    f'title={item["title"]}'
                )
            return

        if not runs:
            self.stdout.write('No jobs due.')
            return

        failed = []
        for run in runs:
            self.stdout.write(
                f'{run.job_key}\t'
                f'status={run.status}\t'
                f'attempts={run.attempts}\t'
                f'duration_ms={run.duration_ms}'
            )
            if run.error:
                self.stdout.write(f'  error={run.error}')
            if run.status == 'error':
                failed.append(run.job_key)

        if failed:
            raise CommandError(f'Failed jobs: {", ".join(failed)}')

        definitions = get_job_definitions()
        self.stdout.write(self.style.SUCCESS(f'Scheduled jobs checked: {len(definitions)} definitions.'))
