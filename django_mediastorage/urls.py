import re
import warnings

from django.conf import settings
from django.conf.urls.static import static
from django.db.models import Model
from django.urls import URLPattern, path, re_path

from . import settings as mediastorage_settings
from .constants import MediaStorageMode
from .storage import inventory
from .views.files import ProtectedFileView
from .views.http_forward_auth import HTTPForwardAuthView


def build_patterns():
    yield from inventory.url_patterns(settings.MEDIA_URL)

    if mediastorage_settings.REGISTER_URLPATTERN_MEDIA_URL:
        yield re_path(
            r"^%s(?P<path>.*)$" % re.escape(settings.MEDIA_URL.lstrip("/")),
            ProtectedFileView.as_view(),
        )

    if mediastorage_settings.REGISTER_URLPATTERN_PUBLIC_URL:
        if not settings.DEBUG:
            warnings.warn(
                "Public media root pattern uses django's `static` url pattern, which will never be served when DEBUG is off. The `URL_PATTERN_PUBLIC_MEDIA_ROOT` setting will likely not have any effect. Consider serving the path directly from your web server (nginx, traefik, ...) instead",
                RuntimeWarning,
                stacklevel=1,
            )
        yield from static(
            mediastorage_settings.PUBLIC_URL,
            document_root=mediastorage_settings.PUBLIC_ROOT,
        )

    if mediastorage_settings.MODE == MediaStorageMode.http_forward_auth:
        yield path(
            mediastorage_settings.FORWARD_AUTH_ENDPOINT_PATH.lstrip("/"),
            HTTPForwardAuthView.as_view(),
        )


def protected_file_path(route: str, model: type[Model], field_name: str) -> URLPattern:
    """
    get a URLPattern for the respective model field
    the field must be one of those from `filestorage.fields`
    """
    return model._meta.get_field(field_name).url_pattern(route)
