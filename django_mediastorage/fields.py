from django.db import models
from django.db.models.fields.files import FieldFile, ImageFieldFile

from .storage.fields import (
    ProtectedFieldFileMixin,
    ProtectedStorageMixin,
    PublicStorageMixin,
)


class ProtectedFieldFile(ProtectedFieldFileMixin, FieldFile):
    pass


class ProtectedImageFieldFile(ProtectedFieldFileMixin, ImageFieldFile):
    pass


class ProtectedFileField(ProtectedStorageMixin, models.FileField):
    attr_class = ProtectedFieldFile


class ProtectedImageField(ProtectedStorageMixin, models.ImageField):
    attr_class = ProtectedImageFieldFile


class PublicFileField(PublicStorageMixin, models.FileField):
    pass


class PublicImageField(PublicStorageMixin, models.ImageField):
    pass
