"""
The inventory keeps track of all directories used.

It ensures that no two file fields use the same directory unless they share the same view
for these files as well. Furthermore, different models are also prohibited from using the
same directory. Note that only the upload_to paths are evaluated for this purpose.

The inventory can find the associated view for any file, provided that a view has been
registered or generated with the file field. This is sometimes used by ProtectedStorage to
get URLs for its FieldFiles.

Furthermore, the inventory keeps record of all paths used.

To register new directories or access inventory information, use the methods provided
in this module.
"""

import importlib
import logging
import os
import warnings
from collections.abc import Iterable
from pathlib import Path
from typing import Optional, Union

from django.core.files.storage import FileSystemStorage
from django.db import models
from django.urls import URLPattern

from .. import settings as mediastorage_settings
from ..constants import ProtectionClass
from ..views.files import BasicFileView

logger = logging.getLogger(__name__)


def raise_inventory_error(error_str: str):
    # TODO: Implement all of these as checks, if possible
    #   When this is done, remove the ENABLE_INVENTORY_CHECKS setting
    if mediastorage_settings.ENABLE_INVENTORY_CHECKS:
        raise ValueError(error_str)


def _get_view(view: Union[str, type[BasicFileView]]) -> Optional[type[BasicFileView]]:
    if isinstance(view, str):
        try:
            module_name, view_name = view.rsplit(".", 1)
            module = importlib.import_module(module_name)
            return module.__getattribute__(view_name)
        except ImportError:
            # todo: have a checks.Error in this case
            logger.error(f"failed to import registered view {view}")
            return None
    return view


class InventoryRecord:
    """
    Record in the inventory.

    This is essentially a dataclass, but has some logic for merging with other records,
    as well as lazy-import for view references (which can avoid circular imports).
    """

    def __init__(
        self,
        storage: type[FileSystemStorage],
        directory: Path,
        protection_class: ProtectionClass,
        model: type[models.Model],
        field_name: str,
        view_ref: Optional[Union[str, type[BasicFileView]]],
    ):
        # need to handle empty path separately as it does not cast to None
        # (it's basically '.')
        if not directory or directory == Path(""):
            # this can happen during migrations; no need to throw a warning in this case
            if model.__module__ != "__fake__":
                warnings.warn(
                    f"Storing files from {model}.{field_name} in storage root."
                    f"set upload_to to a subdirectory.",
                    stacklevel=6,
                )

        self.storage = storage
        self.directory = directory
        self.protection_class = protection_class
        self.model_field_names = {(model, field_name)}
        self.view_ref = view_ref
        self._view_initialized = view_ref is None

    @property
    def document_root(self) -> str:
        return str(self.storage.location)

    def merge_with_record(self, other):
        if self.directory != other.directory:
            raise_inventory_error(
                "Error: trying to merge records of two different directories"
            )
        if self.storage.__class__ != other.storage.__class__:
            raise_inventory_error(
                "Error: trying to merge records of two different storages"
            )
        protection_class = max(self.protection_class, other.protection_class)
        self.storage = other.storage

        # check if both sides have models that aren't accepted by the other
        # ignore fake models that can occur during migrations
        self_models = {m for m, f in self.model_field_names if m.__module__ != "__fake__"}
        other_models = {
            m for m, f in other.model_field_names if m.__module__ != "__fake__"
        }
        if self_models.difference(other_models) and other_models.difference(self_models):
            if protection_class != ProtectionClass.PUBLIC:
                raise_inventory_error(
                    f"Error: cannot have different models use the same upload directory: "
                    f"{next(iter(self_models))} and {next(iter(other_models))} are "
                    f"storing files into {self.full_directory}"
                )
        if self.view_ref != other.view_ref:
            # ignore this case during migrations (i.e., when all models in self or other are fake)
            if self_models and other_models:
                raise_inventory_error(
                    f"Error: trying to have two different views use the same upload "
                    f"directory: {self.view_ref} and {other.view_ref} into "
                    f"{self.full_directory}"
                )
            self.protection_class = protection_class
        self.model_field_names.update(other.model_field_names)

    @property
    def view(self) -> Optional[type[BasicFileView]]:
        # it's possible that view_ref stays None even after lazy loading
        # therefore, we'll need to store the information "is initialized" separately
        if self._view_initialized:
            return self.view_ref
        if self.view_ref is not None:
            self.view_ref = _get_view(self.view_ref)
        self._view_initialized = True
        return self.view_ref

    @property
    def full_directory(self) -> Path:
        return Path(self.document_root, self.directory)

    @property
    def full_field_identifiers(self) -> Iterable[str]:
        for model, field_name in self.model_field_names:
            yield f"{model._meta.app_label}.{model.__name__}.{field_name}"

    def get_url(self, path) -> str:
        view = self.view
        if view is None:
            return None
        return view.get_url(path)

    def url_pattern(self, url_prefix: str) -> Optional[URLPattern]:
        """
        Derive a URL pattern based on a global url_prefix and this record's directory.

        Do not return anything if protection_class is PUBLIC or
        the respective view is set to not be registered
        """
        if self.protection_class == ProtectionClass.PUBLIC:
            return None
        view = self.view
        url_prefix = url_prefix.strip("/") + "/"
        if view is None:
            return None
        if not view.REGISTER_IN_GENERAL_MEDIA_PATH:
            return None
        return self.view.url_pattern(url_prefix)

    def __str__(self):
        return f"InventoryRecord({self.full_directory})"


class FileInventory:
    """
    Inventory to keep track of all directories used by protected fields.

    Used for generating URLs for ProtectedFileStorage backend, as well as to get a list
    of all directories and the type of files they contain.
    """

    def __init__(self):
        self._entries: dict[Path, InventoryRecord] = {}

    def add_protected_dir(self, record: InventoryRecord) -> InventoryRecord:
        """
        Add directory to records.

        In case multiple fields use the same directory and view, always assume the highest
        protection class.
        """
        if record.directory not in self._entries:
            self._entries[record.directory] = record
            return record

        existing_record = self._entries[record.directory]
        existing_record.merge_with_record(record)
        return existing_record

    def list_records(self) -> Iterable[InventoryRecord]:
        return iter(self._entries.values())

    def get_matching_record(self, path: Path) -> Optional[InventoryRecord]:
        # find the path with the longest common prefix that `path` is inside of
        matching_entries = [p for p in self._entries.keys() if path.is_relative_to(p)]
        if not matching_entries:
            return None
        best_match = max(
            matching_entries,
            key=lambda i: len(os.path.commonpath([i, path])),
        )
        return self._entries[best_match]

    def get_record_for_path(self, path: Path) -> Optional[InventoryRecord]:
        return self._entries.get(path)

    def url_patterns(self, route: str) -> Iterable[URLPattern]:
        for record in self._entries.values():
            pattern = record.url_pattern(route)
            if pattern is not None:
                yield pattern


_file_inventory = FileInventory()


def register_protected_dir(
    storage: type[FileSystemStorage],
    directory: Path,
    protection_class: ProtectionClass,
    model: type[models.Model],
    field_name: str,
    view_ref: Optional[Union[str, type[BasicFileView]]],
) -> InventoryRecord:
    """
    register a new directory
    """
    record = InventoryRecord(
        storage=storage,
        directory=directory,
        protection_class=protection_class,
        model=model,
        field_name=field_name,
        view_ref=view_ref,
    )
    if model.__module__ != "__fake__":
        record = _file_inventory.add_protected_dir(record)
    return record


def get_matching_record(path: Union[str, Path]) -> Optional[InventoryRecord]:
    """
    Get the best inventory record for this path.

    The best record is the one that shares the longest common prefix.

    Note that like everything, the path should start relative to the storage's document
    root.
    """
    return _file_inventory.get_matching_record(Path(path))


def get_record_for_path(path: Union[str, Path]) -> Optional[InventoryRecord]:
    """
    Get the record exactly matching the given path.

    Path must be relative to the storage's document root.
    """
    return _file_inventory.get_record_for_path(Path(path))


def list_records() -> Iterable[InventoryRecord]:
    """
    Get a list of all available records.
    """
    return _file_inventory.list_records()


def url_patterns(route: str) -> list[URLPattern]:
    """
    Get URL Patterns for a general media URL path prefix for all registered views

    Does not include Views with REGISTER_IN_GENERAL_MEDIA_PATH==False
    """
    return list(_file_inventory.url_patterns(route))
