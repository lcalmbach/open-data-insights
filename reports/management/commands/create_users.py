from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()

class Command(BaseCommand):
    help = "Creates a default admin and a normal user for development"

    def handle(self, *args, **options):
        users_to_create = [
            {
                'email': 'lcalmbach@gmail.com',
                'password': 'password',
                'first_name': 'Lukas',
                'last_name': 'Calmbach',
                'country': 'Switzerland',
                'is_superuser': True,
                'is_staff': True
            },
            {
                'email': 'lukas.calmbach@bs.ch',
                'password': 'password',
                'first_name': 'Lukas',
                'last_name': 'Calmbach',
                'country': 'Switzerland',
                'is_superuser': False,
                'is_staff': False
            }
        ]

        for user_data in users_to_create:
            if User.objects.filter(email=user_data['email']).exists():
                self.stdout.write(self.style.WARNING(f"User {user_data['email']} already exists."))
                continue

            user = User.objects.create_user(
                email=user_data['email'],
                password=user_data['password'],
                first_name=user_data['first_name'],
                last_name=user_data['last_name'],
                country=user_data.get('country', '')
            )
            if user_data['is_superuser']:
                user.is_superuser = True
                user.is_staff = True
                user.save()
                self.stdout.write(self.style.SUCCESS(f"Created admin user: {user.email}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"Created normal user: {user.email}"))
