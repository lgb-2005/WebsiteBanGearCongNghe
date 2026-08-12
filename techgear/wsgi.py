"""
WSGI config for techgear project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os
from pathlib import Path

from django.core.wsgi import get_wsgi_application


def _load_env():
    env_path = Path(__file__).resolve().parent.parent / '.env'
    if env_path.exists():
        for line in env_path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'techgear.settings')

application = get_wsgi_application()
