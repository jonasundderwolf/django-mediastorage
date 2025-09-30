import json
from collections.abc import Iterable

from django.core.management.base import BaseCommand

from ...storage.inventory import InventoryRecord, list_records


class Command(BaseCommand):
    help = "List all files, where they come from, and their protection class"

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Output as JSON")

    def _print(self, records: Iterable[InventoryRecord]):
        for record in sorted(records, key=lambda record: record.full_directory):
            self.stdout.write(
                f"{record.full_directory}  {record.protection_class.name}  {', '.join(record.full_field_identifiers)}"
            )

    def _output_json(self, records: Iterable[InventoryRecord]):
        self.stdout.write(
            json.dumps(
                [
                    {
                        "directory": str(record.full_directory),
                        "protection_class": record.protection_class.name,
                        "fields": list(record.full_field_identifiers),
                    }
                    for record in records
                ]
            )
        )

    def handle(self, *args, **options):
        if options.get("json"):
            self._output_json(list_records())
        else:
            self._print(list_records())
