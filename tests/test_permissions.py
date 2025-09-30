from collections.abc import Iterable

import factory
import pytest
from django.db import models
from rest_framework.permissions import BasePermission

from django_mediastorage.fields import ProtectedFileField
from django_mediastorage.views.files import RestrictedFileView

from .utils import group_permission


@pytest.fixture
def permissions_check_class_generator(example_app):
    def generate_class_and_factory(
        permission_classes: Iterable[type[BasePermission]],
    ) -> tuple[type[models.Model], factory.django.DjangoModelFactory]:
        class PermissionCheckTestModel(models.Model):
            class Meta:
                app_label = "example_app"

            file_field = ProtectedFileField(
                upload_to="permission_check",
                generate_view=True,
                permission_classes=permission_classes,
            )

        example_app.migrate()

        class PermissionCheckTestModelFactory(factory.django.DjangoModelFactory):
            class Meta:
                model = PermissionCheckTestModel

            file_field = factory.django.FileField(
                filename="testfile.txt", data="test_content"
            )

        return PermissionCheckTestModel, PermissionCheckTestModelFactory

    yield generate_class_and_factory


def custom_permission(allow: bool):
    class CustomPermission(BasePermission):
        def has_permission(self, request, view):
            return allow

        def has_object_permission(self, request, view, obj):
            return allow

    return CustomPermission


VIEW_TEST_CASES = (
    "user_roles, permission_classes, user_is_authorized",
    [
        ([], [], True),
        ([], [group_permission("group_a")], False),
        (["group_a"], [], True),
        (["group_a"], [group_permission("group_a")], True),
        (
            ["group_a", "group_b"],
            [group_permission("group_a")],
            True,
        ),
        (
            ["group_a"],
            [group_permission("group_a", "group_b")],
            True,
        ),
        (
            ["group_a"],
            [
                group_permission("group_a"),
                group_permission("group_b"),
            ],
            False,
        ),
        ([], [custom_permission(True)], True),
        ([], [custom_permission(False)], False),
    ],
)


@pytest.mark.parametrize(*VIEW_TEST_CASES)
@pytest.mark.django_db
def test_user_permissions_on_view(
    user_factory, rf, user_roles, permission_classes, user_is_authorized
):
    _pc = permission_classes  # needed due to shadowing

    class PermissionTestView(RestrictedFileView):
        DOCUMENT_ROOT = "/tmp"
        UPLOAD_TO = "test"
        REVERSE_PATH_NAME = ""
        PROTECTED_URLPATHROOT = "/protected"

        permission_classes = _pc

    request = rf.get("/tmp/test/testfile.txt")
    request.user = user_factory(groups=user_roles)
    response = PermissionTestView.as_view()(request, path="testfile.txt")

    expected_status = 200 if user_is_authorized else 403

    assert response.status_code == expected_status


@pytest.mark.parametrize(*VIEW_TEST_CASES)
@pytest.mark.django_db
def test_user_permissions_on_generated_view(
    user_factory,
    rf,
    permissions_check_class_generator,
    user_roles,
    permission_classes,
    user_is_authorized,
):
    model, model_factory = permissions_check_class_generator(permission_classes)
    test_object = model_factory()

    request = rf.get("/test_media/permission_check/testfile.txt")
    request.user = user_factory(groups=user_roles)
    response = (
        test_object._meta.get_field("file_field")
        .get_view()
        .as_view()(request, path="testfile.txt")
    )

    expected_status = 200 if user_is_authorized else 403

    assert response.status_code == expected_status
