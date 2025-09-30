import dataclasses
import json
import os
import sys
import unicodedata
from collections.abc import Collection, Iterable
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import models

from ...constants import PUBLIC_ROOT
from ...storage import inventory
from ...storage.inventory import InventoryRecord

try:
    "‼️⚠️✅".encode(sys.stdout.encoding)
    allow_unicode = True
except UnicodeEncodeError:
    allow_unicode = False


def unicode_or_ascii(c: str):
    if allow_unicode:
        if c == "✅":  # need to add a space after this tick
            return f"{c} "
        return c
    if c == "‼️" or c == "⚠️":
        return "!"
    return " "


def tick_or_warning(condition: bool, danger: bool = False):
    if not condition:
        return unicode_or_ascii("✅ ")

    if danger:
        return unicode_or_ascii("‼️")

    return unicode_or_ascii("⚠️")


ua = unicode_or_ascii
tw = tick_or_warning


@dataclasses.dataclass
class RecordResult:
    record: InventoryRecord
    files_missing_on_disk: dict[tuple[type[models.Model], str], Collection[str]]
    files_missing_in_database: Collection[str]

    def as_dict(self) -> dict:
        return {
            "files_missing_on_disk": {
                f"{model._meta.app_label}.{model._meta.model_name}.{field}": list(
                    filenames
                )
                for (model, field), filenames in self.files_missing_on_disk.items()
            },
            "files_missing_in_database": list(self.files_missing_in_database),
        }

    def result_print_lines(self) -> Iterable[str]:
        subheading = f"Subdirectory {self.record.full_directory}"
        yield ""
        yield f"  {subheading}"
        yield "  " + "-" * len(subheading)

        if self.files_missing_in_database:
            yield f"  {ua('⚠️')} Found files on disk that are missing in database:"
            for filename in sorted(self.files_missing_in_database):
                yield f"      {filename}"
        else:
            yield f"  {ua('✅')} No files on disk that are missing in database"

        if self.files_missing_on_disk:
            yield f"  {ua('‼️')} Found files from database that are missing on disk:"
            for (model, field), filenames in sorted(
                self.files_missing_on_disk.items(),
                key=lambda x: (
                    x[0][0]._meta.app_label,
                    x[0][0]._meta.model_name,
                    x[0][1],
                ),
            ):
                for filename in sorted(filenames):
                    yield f"      {filename} ({model._meta.app_label}.{model._meta.model_name}.{field})"
        else:
            yield f"  {ua('✅')} No files from database that are missing on disk"

    def summary_print_lines(self) -> Iterable[str]:
        if self.is_clean():
            yield f"→ {ua('✅')} subdirectory {self.record.full_directory} clean"
            return

        yield f"→ subdirectory {self.record.full_directory}"
        yield f"--→ {tw(self.files_missing_in_database)} Files on disk that are missing in database: {len(self.files_missing_in_database)}"

        if self.files_missing_on_disk:
            for (model, field), filenames in sorted(
                self.files_missing_on_disk.items(),
                key=lambda x: (
                    x[0][0]._meta.app_label,
                    x[0][0]._meta.model_name,
                    x[0][1],
                ),
            ):
                yield f"--→ {tw(filenames, True)} Files from {model._meta.app_label}.{model._meta.model_name}.{field} missing on disk: {len(filenames)}"
        else:
            yield f"--→ {ua('✅')} Files missing on disk: 0"

    def is_clean(self):
        return not (self.files_missing_on_disk or self.files_missing_in_database)


@dataclasses.dataclass
class StorageResult:
    document_root: Path
    record_results: dict[str, RecordResult]
    files_in_document_root: Collection[str]
    unknown_directories_in_document_root: Collection[str]

    def as_dict(self) -> dict:
        return {
            "record_results": {
                directory: r.as_dict() for directory, r in self.record_results.items()
            },
            "files_in_document_root": list(self.files_in_document_root),
            "unknown_directories_in_document_root": list(
                self.unknown_directories_in_document_root
            ),
        }

    def result_print_lines(self) -> Iterable[str]:
        heading = str(self.document_root)
        yield ""
        yield heading
        yield "=" * len(heading)

        if self.files_in_document_root:
            yield f"  {ua('⚠️')} Found files in document root:"
            for filename in sorted(self.files_in_document_root):
                yield f"      {filename}"
        else:
            yield f"  {ua('✅')} No files found in document root"

        if self.unknown_directories_in_document_root:
            yield f"  {ua('⚠️')} Found unknown directories in document root:"
            for directory in sorted(self.unknown_directories_in_document_root):
                yield f"      {directory}"
        else:
            yield f"  {ua('✅')} No unknown directories found in document root"

        for _, record_result in sorted(self.record_results.items()):
            yield from record_result.result_print_lines()

    def summary_print_lines(self) -> Iterable[str]:
        if (
            all(r.is_clean for r in self.record_results.values())
            and not self.files_in_document_root
            and not self.unknown_directories_in_document_root
        ):
            yield ""
            yield f"{ua('✅')} {self.document_root}"
            return

        yield ""
        yield f"{self.document_root}"
        yield f"→ {tw(self.files_in_document_root)} files in document root: {len(self.files_in_document_root)}"
        yield f"→ {tw(self.unknown_directories_in_document_root)} unknown directories in document root: {len(self.unknown_directories_in_document_root)}"
        for _directory, record_result in sorted(self.record_results.items()):
            yield from record_result.summary_print_lines()


class Command(BaseCommand):
    help = "List all files, where they come from, and their protection class"

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Output as JSON")
        parser.add_argument("--summary", action="store_true", help="Only print a summary")

    def _examine_record(self, record: InventoryRecord):
        files_missing_on_disk = {}
        files_missing_in_database = {
            unicodedata.normalize(
                "NFC", os.path.join(dirpath, filename)[len(record.document_root) + 1 :]
            )
            for dirpath, dirnames, filenames in os.walk(record.full_directory)
            for filename in filenames
        }

        for model, field in record.model_field_names:
            for obj in model.objects.only(field).exclude(**{field: ""}):
                field_file = getattr(obj, field)
                if field_file.storage.exists(field_file.name):
                    files_missing_in_database.remove(field_file.name)
                    continue
                if (model, field) in files_missing_on_disk:
                    files_missing_on_disk[(model, field)].append(field_file.name)
                else:
                    files_missing_on_disk[(model, field)] = [field_file.name]

        return RecordResult(
            record=record,
            files_missing_on_disk=files_missing_on_disk,
            files_missing_in_database=files_missing_in_database,
        )

    def _examine_directory(self, document_root: Path, ignore: Iterable[str] = None):
        if ignore is None:
            ignore = set()

        records = [
            r for r in inventory.list_records() if Path(r.document_root) == document_root
        ]
        record_directories = {str(r.directory) for r in records}
        existent_directories = {
            d for d in os.listdir(document_root) if os.path.isdir(Path(document_root, d))
        }
        known_directories = existent_directories.intersection(
            record_directories
        ).difference(ignore)
        unknown_directories = existent_directories.difference(
            record_directories
        ).difference(ignore)
        files = {
            f for f in os.listdir(document_root) if os.path.isfile(Path(document_root, f))
        }.difference(ignore)

        return StorageResult(
            document_root=document_root,
            record_results={
                str(d): self._examine_record(inventory.get_record_for_path(d))
                for d in known_directories
            },
            files_in_document_root=files,
            unknown_directories_in_document_root=unknown_directories,
        )

    def _examine_all(self):
        def results():
            for document_root, ignore in [
                (Path(settings.MEDIA_ROOT), [settings.PUBLIC_MEDIA_SUBDIR]),
                (Path(PUBLIC_ROOT()), []),
            ]:
                yield self._examine_directory(document_root, ignore=ignore)

        def yielder():
            if self.output_summary_only:
                for result in results():
                    yield from result.summary_print_lines()
            else:
                for result in results():
                    yield from result.result_print_lines()

        if self.output_json:
            json.dump({str(r.document_root): r.as_dict() for r in results()}, self.stdout)
        else:
            self.stdout.writelines(yielder())

    def handle(self, *args, **options):
        self.output_json = options.get("json", False)
        self.output_summary_only = options.get("summary", False)
        self._examine_all()
