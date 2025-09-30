from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect
from django.utils.encoding import escape_uri_path
from django.views.static import serve

from . import settings as mediastorage_settings
from .constants import MediaStorageMode


class HttpResponseXAccelRedirect(HttpResponse):
    """
    HttpResponse that returns an X-Accel-Redirect to the given HTTP path
    """

    def __init__(self, target_path: str, *args, **kwargs):
        kwargs["content_type"] = ""
        super().__init__(*args, **kwargs)
        self["X-Accel-Redirect"] = escape_uri_path(target_path)


def build_file_response(
    request, path: Path, document_root: Path, protected_url_path: str
):
    """
    A response for a file.

    In debug mode, the file is returned through django directly. In non-debug mode, it
    instead uses X-Accel-Redirect to direct a reverse proxy to return a file located
    inside a protected path.

    It is assumed that `document_root` and `protected_url_path` point to the same
    directory – `document_root` being a path readable for Django, and `protected_url_path`
    being a location inside nginx that is configured as "internal".

    `path` is the relative path to the target file inside that directory.

    The `request` must be provided for handling caching instructions.

    This function does not do any authentication or authorization checks.
    """
    if settings.DEBUG:
        return serve(request, path, document_root)

    match mediastorage_settings.MODE:
        case MediaStorageMode.x_accel_redirect:
            return HttpResponseXAccelRedirect(f"/{protected_url_path.strip('/')}/{path}")
        case MediaStorageMode.http_forward_auth:
            # normally, no request would be redirected here when it's inside
            # MEDIA_URL. The use case for this response is a custom FileView that
            # is serving files outside of the media directory. In this case, we should
            # redirect the browser towards a URL that can actually be served.
            return HttpResponseRedirect(f"/{protected_url_path.strip('/')}/{path}")
