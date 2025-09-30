MEDIA_ROOT = "/tmp/django_mediastorage_pytest_media"
MEDIA_URL = "/media/"

MEDIASTORAGE = {
    "MODE": "x-accel-redirect",  # todo: implement
    "FORWARD_AUTH_ENDPOINT_PATH": "/auth/",
    "ENABLE_INVENTORY_CHECKS": True,
    "REGISTER_URLPATTERN_MEDIA_URL": False,
    "REGISTER_URLPATTERN_PUBLIC_URL": False,
    "FILESERVER_MEDIA_URL": "/protected/",
    "PUBLIC_URL": "/public/",
}

INSTALLED_APPS = (
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django_mediastorage",
)

ROOT_URLCONF = "tests.urls"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "file:memorydb_default?mode=memory&cache=shared",
    }
}
