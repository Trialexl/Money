from django.conf import settings
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from .models import CustomUser


class CustomUserParityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_superuser(
            username='users-admin',
            email='users-admin@example.com',
            password='adminpass123',
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin_user)

    def test_create_user_supports_tax_id(self):
        response = self.client.post(
            '/api/v1/users/',
            {
                'username': 'contractor',
                'password': 'Secretpass123',
                'full_name': 'ООО Ромашка',
                'status': CustomUser.COMPANY,
                'tax_id': '7701234567',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['tax_id'], '7701234567')
        self.assertEqual(CustomUser.objects.get(username='contractor').tax_id, '7701234567')

    def test_create_user_without_password_creates_inactive_login_capability(self):
        response = self.client.post(
            '/api/v1/users/',
            {
                'username': 'contractor-no-password',
                'full_name': 'ООО Без Пароля',
                'status': CustomUser.COMPANY,
                'tax_id': '7701234568',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        user = CustomUser.objects.get(username='contractor-no-password')
        self.assertFalse(user.has_usable_password())

    def test_create_user_rejects_invalid_tax_id(self):
        response = self.client.post(
            '/api/v1/users/',
            {
                'username': 'broken',
                'password': 'Secretpass123',
                'full_name': 'Некорректный ИНН',
                'status': CustomUser.PRIVATE_PERSON,
                'tax_id': '77AB',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('tax_id', response.data)

    def test_profile_includes_tax_id(self):
        profile_user = CustomUser.objects.create_user(
            username='profile-user',
            password='Secretpass123',
            full_name='Иван Иванов',
            status=CustomUser.PRIVATE_PERSON,
            tax_id='123456789012',
        )
        self.client.force_authenticate(profile_user)

        response = self.client.get('/api/v1/profile/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['user']['tax_id'], '123456789012')

    def test_profile_requires_authentication(self):
        response = APIClient().get('/api/v1/profile/')

        self.assertEqual(response.status_code, 401)

    def test_patch_user_supports_is_active_for_onec_deactivation(self):
        user = CustomUser.objects.create_user(
            username='one-c-user',
            password='Secretpass123',
            full_name='Удаляемый контрагент',
            status=CustomUser.PRIVATE_PERSON,
            tax_id='123456789012',
        )

        response = self.client.patch(
            f'/api/v1/users/{user.id}/',
            {
                'is_active': False,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_patch_user_without_password_keeps_existing_password(self):
        user = CustomUser.objects.create_user(
            username='keep-password',
            password='Secretpass123',
            full_name='Контрагент без смены пароля',
            status=CustomUser.PRIVATE_PERSON,
            tax_id='123456789012',
        )

        response = self.client.patch(
            f'/api/v1/users/{user.id}/',
            {
                'full_name': 'Контрагент обновленный',
                'is_active': False,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.full_name, 'Контрагент обновленный')
        self.assertFalse(user.is_active)
        self.assertTrue(user.check_password('Secretpass123'))

    def test_openapi_schema_contains_logout_endpoint(self):
        response = self.client.get('/api/schema/')

        self.assertEqual(response.status_code, 200)
        self.assertIn('/api/v1/auth/logout/', response.content.decode('utf-8'))


class TokenAuthenticationCompatibilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_superuser(
            username='token-admin',
            email='token-admin@example.com',
            password='adminpass123',
        )
        cls.token = Token.objects.create(user=cls.admin_user)

    def test_drf_token_authentication_works_for_api(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

        response = client.get('/api/v1/users/')

        self.assertEqual(response.status_code, 200)


class CookieAuthenticationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_superuser(
            username='cookie-admin',
            email='cookie-admin@example.com',
            password='adminpass123',
        )

    def test_login_sets_http_only_auth_cookies(self):
        client = APIClient()

        response = client.post('/api/v1/auth/token/', {
            'username': 'cookie-admin',
            'password': 'adminpass123',
        }, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertIn(settings.AUTH_ACCESS_COOKIE_NAME, response.cookies)
        self.assertIn(settings.AUTH_REFRESH_COOKIE_NAME, response.cookies)
        self.assertIn(settings.AUTH_SESSION_COOKIE_NAME, response.cookies)
        self.assertTrue(response.cookies[settings.AUTH_ACCESS_COOKIE_NAME]['httponly'])
        self.assertTrue(response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]['httponly'])
        self.assertFalse(response.cookies[settings.AUTH_SESSION_COOKIE_NAME]['httponly'])

    def test_profile_can_use_cookie_jwt(self):
        client = APIClient()
        login_response = client.post('/api/v1/auth/token/', {
            'username': 'cookie-admin',
            'password': 'adminpass123',
        }, format='json')
        self.assertEqual(login_response.status_code, 200)

        response = client.get('/api/v1/profile/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['user']['username'], 'cookie-admin')

    def test_refresh_uses_refresh_cookie_when_body_is_empty(self):
        client = APIClient()
        login_response = client.post('/api/v1/auth/token/', {
            'username': 'cookie-admin',
            'password': 'adminpass123',
        }, format='json')
        self.assertEqual(login_response.status_code, 200)

        response = client.post('/api/v1/auth/refresh/', {}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertIn(settings.AUTH_ACCESS_COOKIE_NAME, response.cookies)

    def test_logout_clears_auth_cookies_without_body_refresh(self):
        client = APIClient()
        login_response = client.post('/api/v1/auth/token/', {
            'username': 'cookie-admin',
            'password': 'adminpass123',
        }, format='json')
        self.assertEqual(login_response.status_code, 200)

        response = client.post('/api/v1/auth/logout/', {}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.cookies[settings.AUTH_ACCESS_COOKIE_NAME]['max-age'], 0)
        self.assertEqual(response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]['max-age'], 0)
        self.assertEqual(response.cookies[settings.AUTH_SESSION_COOKIE_NAME]['max-age'], 0)
