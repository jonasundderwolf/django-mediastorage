import logging
from functools import cached_property
from pathlib import Path
from typing import Optional, Union

from django.conf import settings
from django.core.files.storage import FileSystemStorage

from .. import settings as mediastorage_settings
from . import inventory

logger = logging.getLogger(__name__)


class PublicStorage(FileSystemStorage):
    """
    Storage Backend to use for files that can be publicly available

    FileSystemStorage that uses PUBLIC_ROOT and PUBLIC_URL
    """

    def __init__(self):
        super().__init__(
            location=None,
            base_url=self.url_root,
            file_permissions_mode=None,
            directory_permissions_mode=None,
        )

    @cached_property
    def base_location(self):
        return mediastorage_settings.PUBLIC_ROOT

    @property
    def url_root(self) -> str:
        return mediastorage_settings.PUBLIC_URL


class ProtectedStorage(FileSystemStorage):
    """
    Storage backend to use for files that shouldn't be public.

    Enables the ProtectedFileField and ProtectedImageField URL function when used in
    conjunction with a ProtectedFieldView (see this documentation for more information).
    """

    def __init__(self):
        super().__init__(
            location=None,
            base_url=None,
            file_permissions_mode=None,
            directory_permissions_mode=None,
        )

    @cached_property
    def base_location(self):
        return settings.MEDIA_ROOT

    @property
    def url_root(self) -> str:
        return mediastorage_settings.FILESERVER_MEDIA_URL

    def url(self, name: Optional[Union[str, Path]]) -> Optional[str]:
        if name is None:
            return None
        record = inventory.get_matching_record(Path(name))
        return record.get_url(name)
