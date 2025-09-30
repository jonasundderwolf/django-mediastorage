from collections.abc import Iterable
from pathlib import Path
from typing import Optional, Union

from django.core import checks
from django.urls import URLPattern
from rest_framework.permissions import BasePermission

from ..constants import ProtectionClass
from ..views.files import BasicFileView
from ..views.generator import generate_view_class
from .storage import ProtectedStorage, PublicStorage, inventory


def _clean_upload_to_path(path: Union[str, Path]) -> Path:
    """
    cut an "upload_to" path so that only directories before the first dynamic folder
    remain (e.g., if using "%Y" or similar)
    """
    path = Path(path)
    parts = path.parts
    for i in range(len(parts)):
        if "%" in parts[i]:
            return Path(*parts[:i])
    return path


class ProtectedFieldFileMixin:
    """
    Mixin for FieldFiles that avoids needing to ask the storage for URL and instead
    gets the URL from the file field directly.
    """

    @property
    def url(self):
        if self.name is None:
            return None
        return self.field.get_url(self.name) or super().url


class ProtectedStorageMixin:
    """
    Mixin for FileField subclasses to use the ProtectedStorage as storage backend and
    register themselves to the file inventory.

    Parameters
    ----------
    upload_to:
        Same as FileField
    protection_class:
        ProtectionClass of the files stored in this field
    view:
        View or import-reference to a BasicFileView associated with this field
    generate_view:
        Set to True to generate a view. Cannot be used together with 'view'. Will generate
        BasicFileView, ProtectedFileView, or RestrictedFileView depending on
        protection_class and restrict_to_roles
    permission_classes:
        Role Restriction to use when generating a view. Cannot be used together with
        'view'. Must be used together with 'generate_view'.
    register_generated_view_in_media:
        when generating a view, set REGISTER_IN_GENERAL_MEDIA_PATH to this value. Cannot
        be used together with 'view'. Must be used together with 'generate_view'.
    """

    def __init__(
        self,
        protection_class: ProtectionClass = ProtectionClass.CONFIDENTIAL,
        view: Optional[Union[str, type[BasicFileView]]] = None,
        generate_view: bool = False,
        permission_classes: Optional[Iterable[type[BasePermission]]] = None,
        register_generated_view_in_general_media_path: Optional[bool] = None,
        **kwargs,
    ):
        protection_class = ProtectionClass(protection_class)

        # store these values to use when continuing in contribute_to_class
        self._upload_to = kwargs.get("upload_to", "")
        self._protection_class = protection_class
        self._view = view
        self._generate_view = generate_view
        self._permission_classes = permission_classes
        self._register_generated_view_in_general_media_path = (
            register_generated_view_in_general_media_path
        )

        if "storage" not in kwargs:
            if protection_class == ProtectionClass.PUBLIC:
                kwargs["storage"] = PublicStorage
            else:
                kwargs["storage"] = ProtectedStorage

        super().__init__(**kwargs)

        # TODO Not sure why FileField attributes are not set automatically, but needed
        # as from Django>=3.2 'attrname' is needed in FieldFile.save()
        # https://github.com/django/django/commit/6599608c4d0befdcb820ddccce55f183f247ae4f
        self.set_attributes_from_name(self.name)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs.update(
            {
                "protection_class": self._protection_class,
                "view": self._view,
                "generate_view": self._generate_view,
                "permission_classes": self._permission_classes,
                "register_generated_view_in_general_media_path": self._register_generated_view_in_general_media_path,
            }
        )
        del kwargs["storage"]
        return name, path, args, kwargs

    # TODO: Test all of these checks
    def check(self, **kwargs):
        errors = super().check(**kwargs)

        if self._view and self._generate_view:
            errors.append(
                checks.Error(
                    "Cannot request generate_view when specifying a view",
                    hint="You need to unset either generate_view or view",
                    obj=self,
                    id="django_mediastorage.ProtectedStorage.E001",
                )
            )

        if self._permission_classes and not self._generate_view:
            errors.append(
                checks.Error(
                    "permission_classes can only be specified when generating a view",
                    hint="You need to either unset permission_classes or set generate_view=True",
                    obj=self,
                    id="django_mediastorage.ProtectedStorage.E002",
                )
            )

        if (
            not self._generate_view
            and self._register_generated_view_in_general_media_path is not None
        ):
            errors.append(
                checks.Error(
                    "register_generated_view_in_media can only be specified when generating a view",
                    hint="You need to either unset register_generated_view_in_media or set generate_view=True",
                    obj=self,
                    id="django_mediastorage.ProtectedStorage.E003",
                )
            )

        if self.is_public and self._permission_classes:
            errors.append(
                checks.Error(
                    "No sense in restricting access to a public file",
                    hint="Either set the protection_class to a ProtectionClass other than "
                    "PUBLIC, or unset permission_classes",
                    obj=self,
                    id="django_mediastorage.ProtectedStorage.E004",
                )
            )

        if (
            self.is_public
            and self._register_generated_view_in_general_media_path is not None
        ):
            errors.append(
                checks.Error(
                    "Cannot register public files to media path",
                    hint="If this file is meant to be publicly accessible, unset "
                    "register_generated_view_in_general_media_path (the file will be "
                    "accessible in the public url pattern). If the file is not meant to"
                    "be publicly accessible, set the ProtectionClass accordingly.",
                    obj=self,
                    id="django_mediastorage.ProtectedStorage.E005",
                )
            )

        if (
            self._view
            and self._view_from_inventory is not None
            and self._view_from_inventory != self._view
        ):
            errors.append(
                checks.Error(
                    f'View "{self._view_from_inventory.__qualname__}" already defined for '
                    f'uploads in "{self._upload_to_clean}". Cannot define two views for the '
                    f"same path.",
                    hint="Change the upload_to directory of one of the affected fields",
                    obj=self,
                    id="django_mediastorage.Inventory.E101",
                )
            )

        return errors

    @property
    def is_public(self) -> bool:
        return self._protection_class == ProtectionClass.PUBLIC

    @property
    def _upload_to_clean(self) -> Path:
        return _clean_upload_to_path(self._upload_to)

    @property
    def _view_from_inventory(self) -> Optional[type[BasicFileView]]:
        existing_record = inventory.get_matching_record(self._upload_to_clean)
        if existing_record is None:
            return None
        return existing_record.view_ref

    def contribute_to_class(self, model, field_name):
        super().contribute_to_class(model, field_name)

        permission_classes = self._permission_classes
        register_generated_view_in_general_media_path = (
            self._register_generated_view_in_general_media_path
        )

        if self._generate_view:
            view = generate_view_class(
                self._view_from_inventory,
                view_name=f"{model._meta.app_label}.{model.__name__}.{field_name}",
                document_root=self.storage.location,
                url_root=self.storage.url_root,
                is_public=self.is_public,
                upload_to=self._upload_to_clean,
                permission_classes=permission_classes,
                register_in_general_media_path=register_generated_view_in_general_media_path,
            )
        else:
            view = self._view
        self._record = inventory.register_protected_dir(
            storage=self.storage,
            directory=self._upload_to_clean,
            protection_class=self._protection_class,
            model=model,
            field_name=field_name,
            view_ref=view,
        )

    def get_view(self) -> Optional[type[BasicFileView]]:
        return self._record.view

    def url_pattern(self, url_prefix: str) -> URLPattern:
        return self._record.view.url_pattern(url_prefix)

    def get_url(self, path: str) -> Optional[str]:
        return self._record.get_url(path)


class PublicStorageMixin(ProtectedStorageMixin):
    _PublicStorageMixin_DEFAULTS = {
        "protection_class": ProtectionClass.PUBLIC,
        "view": None,
        "generate_view": False,
        "permission_classes": None,
    }

    def __init__(self, **kwargs):
        self._original_kwargs = kwargs.copy()
        kwargs.update(self._PublicStorageMixin_DEFAULTS)
        super().__init__(**kwargs)

    def check(self, **kwargs):
        errors = super().check(**kwargs)

        # TODO: Test these checks
        for key, default_value in self._PublicStorageMixin_DEFAULTS.items():
            if key not in self._original_kwargs:
                continue
            errors.append(
                checks.Error(
                    f"PublicFileField cannot override {key}",
                    hint=f"For PublicFileField classes, {key} is forced to be {str(default_value)}. You need to unset this value in your model, or use another field class, like ProtectedFileField",
                    obj=self,
                    id=f"django_mediastorage.PublicStorage.E-{key}",
                )
            )

        return errors

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        for key in self._PublicStorageMixin_DEFAULTS.keys():
            if key in kwargs:
                del kwargs[key]
        return name, path, args, kwargs
