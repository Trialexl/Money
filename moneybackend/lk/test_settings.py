import os

os.environ.setdefault('DJANGO_ALLOW_INSECURE_SETTINGS', '1')

from .settings import *  # noqa: F401,F403

SECRET_KEY = 'ci-test-secret-key-at-least-32-bytes'
DEBUG = False

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]
AUTH_PASSWORD_VALIDATORS = []

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'ci.sqlite3',
        'TEST': {
            'NAME': ':memory:',
        },
    }
}

EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
MEDIA_ROOT = BASE_DIR / 'test-media'

AI_DEFAULT_PROVIDER = 'rule_based'
AI_OPENROUTER_API_KEY = ''
AI_OPENAI_API_KEY = ''
AI_TELEGRAM_BOT_TOKEN = ''
AI_TELEGRAM_BOT_SECRET = ''

INVESTMENT_PRICE_PROVIDER = 'auto'
INVESTMENT_FX_PROVIDER = 'cbr'
