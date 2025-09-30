import posixpath
import re
from pathlib import Path
from typing import Iterable, Optional

from django.conf import settings
from django.http import HttpResponseForbidden
from django.urls import URLPattern, re_path, reverse
from django.views import View
from rest_framework.permissions import BasePermission

from .. import settings as mediastorage_settings
from ..response import build_file_response


class BasicFileView(View):
    """
    A view that returns files, using django_mediastorage.response.build_file_response.

    This class is not intended to be used directly. The four class attributes must be
    adjusted to the use case.

    By default, this class' `get` method expects to be passed a `path` from the URL
    matcher. It will prepend UPLOAD_TO to that path for further handling. For more complex
    handling, override the `_get_path_from_kwargs` method.

    When used together with a ProtectedFileField, UPLOAD_TO should be the same as
    upload_to of the field, and DOCUMENT_ROOT should be the DOCUMENT_ROOT of the file
    storage.

    PROTECTED_URLPATHROOT should point to a URL that is equivalent to the DOCUMENT_ROOT
    for use with X-Accel-Redirect (similar to build_file_response).

    This view will only serve files inside its UPLOAD_TO directory.

    You can use path_kwargs() to get the view and name to pass to a urls.py entry.

    If you need the path "name" to be predictable, override the REVERSE_PATH_NAME
    attribute.

    If you need ProtectedFileField.url to be working, setting the `REVERSE_PATH_NAME` to
    a corresponding url path name in urls.py should be enough. If you have overridden
    _get_path_from_kwargs(), you will need to implement a reversal for that by also
    overriding _get_kwargs_from_path(). If this isn't enough, you could also override
    `get_url()` otherwise.

    Attributes
    ----------
    IS_GENERATED:
        needed by storage.view_generator to mark generated views as generated
    DOCUMENT_ROOT:
        Should be the document root of the associated field's storage.
    UPLOAD_TO:
        Path that all files of this view are inside of. Essentially the same as FileField
        upload_to. See build_file_response() for more details.
    REVERSE_PATH_NAME:
        Reverse path that can be used in django's "reverse" function to point to this
        view.
    PROTECTED_URLPATHROOT:
        URL Prefix that points to the same directory as DOCUMENT_ROOT. See
        build_file_response() for more details.
    REGISTER_IN_GENERAL_MEDIA_PATH:
        Whether to include this view in inventory.url_patterns()
    """

    IS_GENERATED: bool = False

    DOCUMENT_ROOT: str = mediastorage_settings.PUBLIC_ROOT

    UPLOAD_TO: str = ""

    REVERSE_PATH_NAME: Optional[str] = None

    PROTECTED_URLPATHROOT: str = ""

    REGISTER_IN_GENERAL_MEDIA_PATH: bool = False

    @classmethod
    def url_pattern(cls, url_prefix: str) -> URLPattern:
        """
        return re_path entry for urls.py for this view
        """
        if not cls.REVERSE_PATH_NAME:
            cls.REVERSE_PATH_NAME = f"FileView-{cls.__qualname__}"
        return re_path(
            r"^%s/%s/(?P<path>.*)$"
            % (
                re.escape(url_prefix.strip("/")),
                re.escape(str(cls.UPLOAD_TO).strip("/")),
            ),
            view=cls.as_view(),
            name=cls.REVERSE_PATH_NAME,
        )

    @classmethod
    def get_url(cls, path: Path) -> Optional[str]:
        """
        For a given file, get the URL pointing to it.

        Required for URL lookup by ProtectedFileFields.
        """
        if cls.REVERSE_PATH_NAME is None:
            return None
        return reverse(cls.REVERSE_PATH_NAME, kwargs=cls._get_kwargs_from_path(path))

    def _get_path(self) -> Path:
        """
        Construct the path from kwargs.

        Return a relative path inside DOCUMENT_ROOT or PROTECTED_URLPATHROOT,
        respectively.
        """
        return Path(
            self.UPLOAD_TO, posixpath.normpath(str(self.kwargs["path"]).lstrip("/"))
        )

    @classmethod
    def _get_kwargs_from_path(cls, path: Path) -> dict:
        """
        Reverse of _get_path_from_kwargs, used for URL reverse lookup
        """
        return {"path": Path(path).relative_to(cls.UPLOAD_TO)}

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.path = self._get_path()

    def check_access(self):
        """
        Return whether the user is allowed to access the file.

        False will make the view return a 403 response instead of the actual file.

        True will make the view return the file (or x-accel-redirect to the file)
        """
        return True

    def get(self, request, **kwargs):
        if not self.check_access():
            return HttpResponseForbidden()
        return build_file_response(
            request, self.path, Path(self.DOCUMENT_ROOT), self.PROTECTED_URLPATHROOT
        )


class ProtectedFileView(BasicFileView):
    """
    Using the structure of BasicFileView, this view restricts access to its files.

    This class is not intended to be used directly. Subclasses must specify the same
    things as with BasicFileView.

    By default, all authenticated active users are allowed to view the file.

    You can override check_access() if you need to restrict access further than
    that. If you do so, start the override method with
    `if not super().check_access(): return False`.
    """

    DOCUMENT_ROOT: str = settings.MEDIA_ROOT

    PROTECTED_URLPATHROOT: str = mediastorage_settings.FILESERVER_MEDIA_URL

    REGISTER_IN_GENERAL_MEDIA_PATH: bool = True

    def check_access(self) -> bool:
        """
        Return whether the user is allowed to access the file.

        False will make the view return a 403 response instead of the actual file.

        True will make the view return the file (or x-accel-redirect to the file)
        """
        return self.request.user.is_authenticated and self.request.user.is_active


class RestrictedFileView(ProtectedFileView):
    """
    Like ProtectedFileView, but restrict access further by limiting it to only users which
    have the respected access permissions.

    This class is not intended to be used directly. Subclasses must specify the same
    things as with BasicFileView as well as permission_classes

    Attributes
    ----------
    permission_classes :
        List of permissions as in rest_framework's APIView.permission_classes.
    """

    permission_classes: Iterable[type[BasePermission]] = []

    def _get_permissions(self) -> Iterable[BasePermission]:
        for permission_class in self.permission_classes:
            yield permission_class()

    def check_access(self) -> bool:
        # we first check if an authenticated active user is set
        if not super().check_access():
            return False

        # then check user permissions
        for permission in self._get_permissions():
            if not permission.has_permission(self.request, self):
                return False

        return True
