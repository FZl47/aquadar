import sys
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = 'Seed database with Persian test data'

    def _out(self, msg):
        try:
            self.stdout.write(msg)
        except UnicodeEncodeError:
            sys.stdout.buffer.write((msg + '\n').encode('utf-8'))

    def handle(self, *args, **options):
        self._out('[seed] Starting Persian test data...')
        self._create_run_settings()
        farms = self._create_farms()
        self._create_manure_categories()
        users = self._create_users(farms)
        self._create_farm_user_groups(farms, users)
        self._out('[seed] Done.')

    def _create_run_settings(self):
        from apps.public.models import RunSettings
        if RunSettings.objects.exists():
            self._out('  [skip] RunSettings already exists.')
            return
        RunSettings.objects.create(
            wind_speed_more_t=30,
            wind_speed_less_t=2,
            temp_value_more_t=40,
            temp_value_less_t=4,
            expiration_run_time=24,
            create_report_to_supervisor_if_has_problem=True,
            avg_tolerance_run_duration=30,
            require_gps=True,
            allow_code_entry=True,
        )
        self._out('  [ok] RunSettings created.')

    def _create_farms(self):
        from apps.public.models import Farm, Zone, Plot, Outlet

        farms_data = [
            {
                'number': 1,
                'name': 'مزرعه شمالی',
                'pool_size': 5000,
                'discharge_rate': '12.50',
                'zones': [
                    {
                        'number': 1,
                        'name': 'ناحیه الف',
                        'order': 1,
                        'plots': [
                            {
                                'number': 1,
                                'name': 'زمین یک',
                                'avg_run_duration': 45,
                                'boundary': [[36.5010, 51.3010], [36.5020, 51.3010],
                                             [36.5020, 51.3020], [36.5010, 51.3020]],
                                'outlets': 4,
                            },
                            {
                                'number': 2,
                                'name': 'زمین دو',
                                'avg_run_duration': 60,
                                'boundary': [[36.5030, 51.3030], [36.5040, 51.3030],
                                             [36.5040, 51.3040], [36.5030, 51.3040]],
                                'outlets': 3,
                            },
                        ],
                    },
                    {
                        'number': 2,
                        'name': 'ناحیه ب',
                        'order': 2,
                        'plots': [
                            {
                                'number': 3,
                                'name': 'زمین سه',
                                'avg_run_duration': 50,
                                'boundary': [[36.5050, 51.3050], [36.5060, 51.3050],
                                             [36.5060, 51.3060], [36.5050, 51.3060]],
                                'outlets': 5,
                            },
                            {
                                'number': 4,
                                'name': 'زمین چهار',
                                'avg_run_duration': 40,
                                'boundary': [[36.5070, 51.3070], [36.5080, 51.3070],
                                             [36.5080, 51.3080], [36.5070, 51.3080]],
                                'outlets': 3,
                            },
                        ],
                    },
                ],
            },
            {
                'number': 2,
                'name': 'مزرعه جنوبی',
                'pool_size': 8000,
                'discharge_rate': '18.00',
                'zones': [
                    {
                        'number': 1,
                        'name': 'ناحیه یک',
                        'order': 1,
                        'plots': [
                            {
                                'number': 1,
                                'name': 'زمین آفتابی',
                                'avg_run_duration': 55,
                                'boundary': [[36.4010, 51.2010], [36.4020, 51.2010],
                                             [36.4020, 51.2020], [36.4010, 51.2020]],
                                'outlets': 6,
                            },
                            {
                                'number': 2,
                                'name': 'زمین سایه',
                                'avg_run_duration': 35,
                                'boundary': [[36.4030, 51.2030], [36.4040, 51.2030],
                                             [36.4040, 51.2040], [36.4030, 51.2040]],
                                'outlets': 4,
                            },
                        ],
                    },
                    {
                        'number': 2,
                        'name': 'ناحیه دو',
                        'order': 2,
                        'plots': [
                            {
                                'number': 3,
                                'name': 'زمین مرکزی',
                                'avg_run_duration': 65,
                                'boundary': [[36.4050, 51.2050], [36.4060, 51.2050],
                                             [36.4060, 51.2060], [36.4050, 51.2060]],
                                'outlets': 5,
                            },
                        ],
                    },
                ],
            },
        ]

        created_farms = []
        for farm_data in farms_data:
            farm, created = Farm.objects.get_or_create(
                number=farm_data['number'],
                defaults={
                    'name': farm_data['name'],
                    'pool_size': farm_data['pool_size'],
                    'discharge_rate': farm_data['discharge_rate'],
                    'is_active': True,
                },
            )
            if created:
                self._out(f'  [ok] Farm created: {farm.number}')
            created_farms.append(farm)

            for zone_data in farm_data['zones']:
                zone, _ = Zone.objects.get_or_create(
                    farm=farm,
                    number=zone_data['number'],
                    defaults={
                        'name': zone_data['name'],
                        'order': zone_data['order'],
                    },
                )

                for plot_data in zone_data['plots']:
                    plot, _ = Plot.objects.get_or_create(
                        zone=zone,
                        number=plot_data['number'],
                        defaults={
                            'name': plot_data['name'],
                            'avg_run_duration': plot_data['avg_run_duration'],
                            'boundary': plot_data['boundary'],
                        },
                    )

                    if plot.outlets.count() == 0:
                        outlets = [Outlet(plot=plot, number=i)
                                   for i in range(1, plot_data['outlets'] + 1)]
                        Outlet.objects.bulk_create(outlets)

        self._out(f'  [ok] {len(created_farms)} farms with zones/plots/outlets created.')
        return created_farms

    def _create_manure_categories(self):
        from apps.public.models import ManureCategory

        categories = [
            ('کود ازته',
             'کودهای حاوی نیتروژن'),
            ('کود فسفاته',
             'کودهای حاوی فسفر'),
            ('کود پتاسه',
             'کودهای حاوی پتاسیم'),
            ('کود آلی',
             'کودهای طبیعی و ارگانیک'),
            ('کود مرکب',
             'کودهای ترکیبی NPK'),
        ]

        count = 0
        for title, desc in categories:
            _, created = ManureCategory.objects.get_or_create(
                title=title, defaults={'description': desc})
            if created:
                count += 1

        self._out(f'  [ok] {count} manure categories created.')

    def _create_users(self, farms):
        users = {}

        if not User.objects.filter(username='admin').exists():
            admin = User.all_objects.filter(username='admin').first()
            if not admin:
                admin = User.objects.create_superuser(
                    username='admin',
                    password='Admin@1234',
                    first_name='مدیر',
                    last_name='سیستم',
                )
                admin.farms.set(farms)
                self._out('  [ok] Superuser (admin) created. password=Admin@1234')
            users['admin'] = admin

        supervisors_data = [
            {
                'username': 'ahmadi_nazar',
                'first_name': 'محمد',
                'last_name': 'احمدی',
                'phonenumber': '09121234567',
            },
            {
                'username': 'rezaei_nazar',
                'first_name': 'علی',
                'last_name': 'رضایی',
                'phonenumber': '09131234568',
            },
        ]

        watermans_data = [
            {
                'username': 'mohammadi_ab',
                'first_name': 'حسن',
                'last_name': 'محمدی',
                'phonenumber': '09141234569',
            },
            {
                'username': 'karimi_ab',
                'first_name': 'رضا',
                'last_name': 'کریمی',
                'phonenumber': '09151234570',
            },
            {
                'username': 'najafi_ab',
                'first_name': 'زهرا',
                'last_name': 'نجفی',
                'phonenumber': '09161234571',
            },
            {
                'username': 'sadeghi_ab',
                'first_name': 'مهدی',
                'last_name': 'صادقی',
                'phonenumber': '09171234572',
            },
        ]

        users['supervisors'] = []
        for data in supervisors_data:
            user, created = User.objects.get_or_create(
                username=data['username'],
                defaults={
                    'first_name': data['first_name'],
                    'last_name': data['last_name'],
                    'phonenumber': data['phonenumber'],
                    'role': 'supervisor',
                    'is_active': True,
                },
            )
            if created:
                user.set_password('Pass@1234')
                user.save(update_fields=['password'])
                user.farms.set(farms)
                self._out(f'  [ok] Supervisor created: {data["username"]}')
            users['supervisors'].append(user)

        users['watermans'] = []
        for data in watermans_data:
            user, created = User.objects.get_or_create(
                username=data['username'],
                defaults={
                    'first_name': data['first_name'],
                    'last_name': data['last_name'],
                    'phonenumber': data['phonenumber'],
                    'role': 'waterman',
                    'is_active': True,
                },
            )
            if created:
                user.set_password('Pass@1234')
                user.save(update_fields=['password'])
                user.farms.set(farms)
                self._out(f'  [ok] Waterman created: {data["username"]}')
            users['watermans'].append(user)

        return users

    def _create_farm_user_groups(self, farms, users):
        from apps.public.models import FarmUserGroup

        supervisors = users.get('supervisors', [])
        watermans = users.get('watermans', [])

        for i, farm in enumerate(farms):
            title = f'گروه کاربری {farm.name}'
            group, created = FarmUserGroup.objects.get_or_create(
                farm=farm,
                defaults={'title': title},
            )
            if created:
                group.supervisors.set(supervisors)
                half = max(1, len(watermans) // 2)
                assigned = watermans[:half] if i == 0 else watermans[half:]
                group.watermans.set(assigned)
                self._out(f'  [ok] FarmUserGroup created for farm {farm.number}')
