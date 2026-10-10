"""Settings dùng cho test nhanh khi không có MariaDB chạy sẵn.

Dùng bằng: pytest --ds=techgear.test_settings
"""

from techgear.settings import *  # noqa: F403,F401

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}
