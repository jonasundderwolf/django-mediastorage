import pytest
from django.contrib.auth.models import AnonymousUser
from django.db import models
from django.urls import path

from django_mediastorage.fields import ProtectedFileField
from django_mediastorage.urls import protected_file_path
from django_mediastorage.views.files import BaseFileView
from django_mediastorage.views.http_forward_auth import HTTPForwardAuthView

from .utils import group_permission


@pytest.mark.parametrize(
    "user_roles, is_active, is_anonymous, field_name, status_code",
    [
        ([], True, False, "protected_file", 200),
        ([], True, False, "restricted_file", 403),
        (["A"], True, False, "restricted_file", 200),
        (["B"], True, False, "restricted_file", 403),
        ([], True, False, "forbidden_file", 403),
        ([], False, False, "protected_file", 403),
        ([], False, True, "protected_file", 403),
    ],
)
@pytest.mark.django_db
@pytest.mark.urls("tests.urls")
def test_http_forward_auth_applying_permisions(
    user_factory,
    rf,
    set_urlpatterns,
    restore_inventory_afterwards,
    user_roles,
    is_active,
    is_anonymous,
    field_name,
    status_code,
):
    class ForbiddenFileView(BaseFileView):
        # todo: general check in library that all file views have upload_to set in accordance with their respective fields (or other way round)
        UPLOAD_TO = "forbidden_file"  # must match field_name parameter

        def check_access(self):
            return False

    class TestModel(models.Model):
        class Meta:
            app_label = "example_app"

        # note: upload_to must match the available field_name parameters
        protected_file = ProtectedFileField(
            upload_to="protected_file", generate_view=True
        )
        restricted_file = ProtectedFileField(
            upload_to="restricted_file",
            generate_view=True,
            permission_classes=[group_permission("A")],
        )
        forbidden_file = ProtectedFileField(
            upload_to="forbidden_file", view=ForbiddenFileView
        )

    set_urlpatterns(
        [
            path("auth/", HTTPForwardAuthView.as_view()),
            protected_file_path("test_media/", TestModel, field_name),
        ]
    )

    # check if access works for the protected file
    request = rf.get(
        "auth/", headers={"X-Forwarded-Uri": f"/test_media/{field_name}/test.txt"}
    )
    if is_anonymous:
        request.user = AnonymousUser()
    else:
        request.user = user_factory(is_active=is_active, groups=user_roles)
    response = HTTPForwardAuthView.as_view()(request)
    assert response.status_code == status_code
