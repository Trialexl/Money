from datetime import datetime, time, timedelta

from django.db import migrations
from django.utils import timezone


SCHEDULES = {
    'backup.restore_check': (10080, time(4, 20)),
    'investment.fx_refresh': (1440, time(5, 30)),
    'investment.price_refresh': (1440, time(5, 45)),
    'investment.market_health': (1440, time(6, 10)),
    'investment.snapshots_today': (1440, time(6, 40)),
    'investment.telegram_portfolio_report': (1440, time(6, 50)),
}


def apply_lightweight_schedule(apps, schema_editor):
    ScheduledJobState = apps.get_model('ops', 'ScheduledJobState')
    now = timezone.now()
    current_tz = timezone.get_current_timezone()
    today = timezone.localdate(now, current_tz)

    for job_key, (interval_minutes, run_at_time) in SCHEDULES.items():
        next_run_at = timezone.make_aware(
            datetime.combine(today, run_at_time),
            current_tz,
        )
        while next_run_at <= now:
            next_run_at += timedelta(minutes=interval_minutes)

        ScheduledJobState.objects.filter(job_key=job_key).update(
            interval_minutes=interval_minutes,
            run_at_time=run_at_time,
            next_run_at=next_run_at,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0002_schedulerstate'),
    ]

    operations = [
        migrations.RunPython(apply_lightweight_schedule, migrations.RunPython.noop),
    ]
