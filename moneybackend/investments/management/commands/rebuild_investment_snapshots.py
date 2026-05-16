from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_date

from investments.models import InvestmentPortfolio
from investments.services import rebuild_portfolio_snapshots


class Command(BaseCommand):
    help = 'Пересчитать дневные snapshots инвестиционных портфелей.'

    def add_arguments(self, parser):
        parser.add_argument('--portfolio', help='UUID портфеля. Если не указан, пересчитываются все портфели.')
        parser.add_argument('--date-from', help='Дата начала YYYY-MM-DD. По умолчанию первая дата данных портфеля.')
        parser.add_argument('--date-to', help='Дата окончания YYYY-MM-DD. По умолчанию сегодня.')
        parser.add_argument(
            '--allow-stale-prices',
            action='store_true',
            help='Разрешить брать последнюю цену до даты snapshot. По умолчанию нужна цена на дату snapshot.',
        )

    def handle(self, *args, **options):
        portfolio_id = options.get('portfolio')
        date_from = self._parse_date_option(options.get('date_from'), 'date-from')
        date_to = self._parse_date_option(options.get('date_to'), 'date-to')
        portfolio = None
        if portfolio_id:
            portfolio = InvestmentPortfolio.objects.filter(pk=portfolio_id).first()
            if portfolio is None:
                raise CommandError(f'Портфель {portfolio_id} не найден.')

        summary = rebuild_portfolio_snapshots(
            portfolio=portfolio,
            date_from=date_from,
            date_to=date_to,
            price_max_age_days=None if options.get('allow_stale_prices') else 0,
        )
        self.stdout.write(self.style.SUCCESS(
            'Investment snapshots: '
            f'portfolios={summary["portfolios"]}, '
            f'snapshots={summary["snapshots"]}, '
            f'created={summary["created"]}, '
            f'updated={summary["updated"]}, '
            f'skipped={summary["skipped"]}.'
        ))

    @staticmethod
    def _parse_date_option(value, option_name):
        if not value:
            return None
        parsed = parse_date(value)
        if parsed is None:
            raise CommandError(f'Некорректный --{option_name}. Используйте YYYY-MM-DD.')
        return parsed
