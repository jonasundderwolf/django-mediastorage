import os
from pathlib import Path

import pytest
from django.db import models

from django_mediastorage import settings as mediastorage_settings
from django_mediastorage.constants import ProtectionClass
from django_mediastorage.fields import ProtectedFileField, PublicFileField
from django_mediastorage.storage import inventory
from django_mediastorage.views.files import ProtectedFileView

from .utils import group_permission


def test_str_to_view_resolution(restore_inventory_afterwards):
    class TestStrToView(models.Model):
        class Meta:
            app_label = "example_app"

        f = ProtectedFileField(
            upload_to="str_to_view",
            view="django_mediastorage.views.files.ProtectedFileView",
        )

    assert TestStrToView._meta.get_field("f").get_view() == ProtectedFileView


def test_str_to_view_resolution_invalid_view(restore_inventory_afterwards):
    class TestStrToViewInvalid(models.Model):
        class Meta:
            app_label = "example_app"

        f = ProtectedFileField(
            upload_to="str_to_view_invalid", view="nonexisting_package.someView"
        )

    assert TestStrToViewInvalid._meta.get_field("f").get_view() is None


def test_inventory_records(settings, restore_inventory_afterwards):
    class TestInventoryRecordsModel(models.Model):
        class Meta:
            app_label = "example_app"

        public_file = PublicFileField(
            upload_to="test_inventory_records__test_public_file"
        )
        protected_file = ProtectedFileField(
            upload_to="test_inventory_records__test_protected_1"
        )
        much_more_protected_file = ProtectedFileField(
            upload_to="test_inventory_records__test_protected_1",
            protection_class=ProtectionClass.CONFIDENTIAL,
        )

    f_public = TestInventoryRecordsModel._meta.get_field("public_file")
    f_protected = TestInventoryRecordsModel._meta.get_field("protected_file")

    r_public = inventory.get_record_for_path(f_public.upload_to)
    r_protected = inventory.get_matching_record(f_protected.upload_to)

    # check if merged correctly
    assert r_public.model_field_names == {(TestInventoryRecordsModel, "public_file")}
    assert r_protected.model_field_names == {
        (TestInventoryRecordsModel, "protected_file"),
        (TestInventoryRecordsModel, "much_more_protected_file"),
    }

    # test document roots
    assert str(r_public.document_root) == str(
        mediastorage_settings.PUBLIC_ROOT.absolute()
    )
    assert str(r_protected.document_root) == str(Path(settings.MEDIA_ROOT).absolute())

    # test full_directory and directory
    assert (
        r_public.full_directory.absolute()
        == Path(
            mediastorage_settings.PUBLIC_ROOT, "test_inventory_records__test_public_file"
        ).absolute()
    )
    assert (
        r_protected.full_directory.absolute()
        == Path(
            settings.MEDIA_ROOT, "test_inventory_records__test_protected_1"
        ).absolute()
    )

    # test protection class and merging thereof
    assert r_public.protection_class == ProtectionClass.PUBLIC
    assert r_protected.protection_class == ProtectionClass.CONFIDENTIAL

    all_records = inventory.list_records()
    assert r_public in all_records
    assert r_protected in all_records

    # "core" app because tests are located in core
    assert list(r_public.full_field_identifiers) == [
        "example_app.TestInventoryRecordsModel.public_file"
    ]
    assert sorted(r_protected.full_field_identifiers) == sorted(
        [
            "example_app.TestInventoryRecordsModel.protected_file",
            "example_app.TestInventoryRecordsModel.much_more_protected_file",
        ]
    )


@pytest.mark.parametrize(
    "type_l, kwargs_l, type_r, kwargs_r, throws_exception",
    [
        (PublicFileField, {}, ProtectedFileField, {}, True),
        (ProtectedFileField, {}, ProtectedFileField, {}, False),
        (PublicFileField, {}, PublicFileField, {}, False),
        (
            ProtectedFileField,
            {"protection_class": ProtectionClass.INTERNAL},
            ProtectedFileField,
            {"protection_class": ProtectionClass.PRIVATE},
            False,
        ),
        (
            ProtectedFileField,
            {"permission_classes": []},
            ProtectedFileField,
            {"permission_classes": [group_permission("mock_role")]},
            True,
        ),
        (
            ProtectedFileField,
            {"permission_classes": [group_permission("mock_role")]},
            ProtectedFileField,
            {"permission_classes": [group_permission("mock_role")]},
            False,
        ),
        (
            ProtectedFileField,
            {"permission_classes": [group_permission("another_mock_role")]},
            ProtectedFileField,
            {"permission_classes": [group_permission("mock_role")]},
            True,
        ),
    ],
)
def test_directory_sharing_checks_with_view_generation(
    type_l,
    kwargs_l,
    type_r,
    kwargs_r,
    throws_exception,
    settings,
    restore_inventory_afterwards,
):
    settings.FILESTORAGE_ENABLE_INVENTORY_CHECKS = True

    def _test():
        upload_to = f'shared+{os.environ.get("PYTEST_CURRENT_TEST")}'

        class TestClass(models.Model):
            class Meta:
                app_label = "example_app"

            f1 = type_l(upload_to=upload_to, generate_view=True, **kwargs_l)
            f2 = type_r(upload_to=upload_to, generate_view=True, **kwargs_r)

    if throws_exception:
        with pytest.raises(ValueError):
            _test()
    else:
        _test()


def test_directory_sharing_two_models(settings, restore_inventory_afterwards):
    upload_to = f'shared+{os.environ.get("PYTEST_CURRENT_TEST")}'
    settings.FILESTORAGE_ENABLE_INVENTORY_CHECKS = True

    class T1(models.Model):
        class Meta:
            app_label = "example_app"

        f = ProtectedFileField(upload_to=upload_to)

    with pytest.raises(ValueError):

        class T2(models.Model):
            class Meta:
                app_label = "example_app"

            f2 = ProtectedFileField(upload_to=upload_to)


def test_directory_sharing_with_views(settings, restore_inventory_afterwards):
    settings.FILESTORAGE_ENABLE_INVENTORY_CHECKS = True

    class CustomView1(ProtectedFileView):
        pass

    class CustomView2(ProtectedFileView):
        pass

    upload_to = f'shared+{os.environ.get("PYTEST_CURRENT_TEST")}'

    # should be okay
    class T1(models.Model):
        class Meta:
            app_label = "example_app"

        f1 = ProtectedFileField(upload_to=f"{upload_to}1", view=CustomView1)
        f2 = ProtectedFileField(upload_to=f"{upload_to}1", view=CustomView1)

    with pytest.raises(ValueError):

        class T2(models.Model):
            class Meta:
                app_label = "example_app"

            f1 = ProtectedFileField(upload_to=f"{upload_to}2", view=CustomView1)
            f2 = ProtectedFileField(upload_to=f"{upload_to}2", view=CustomView2)
