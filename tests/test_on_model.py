import os
from pathlib import Path

import pytest
from django.db import models
from django.http import Http404
from django.urls import Resolver404, resolve
from django.views.static import serve

from django_mediastorage import settings as mediastorage_settings
from django_mediastorage.constants import MediaStorageMode, ProtectionClass
from django_mediastorage.fields import ProtectedFileField, PublicFileField
from django_mediastorage.urls import build_patterns, protected_file_path
from django_mediastorage.views.files import ProtectedFileView, RestrictedFileView
from django_mediastorage.views.http_forward_auth import HTTPForwardAuthView

from .utils import group_permission


@pytest.mark.django_db
def test_view_generation(protected_file_field_test_model_factory):
    model = protected_file_field_test_model_factory._meta.model

    f_public = model._meta.get_field("public_file_with_view")
    f_protected = model._meta.get_field("protected_file_with_view")
    f_protected_shared = model._meta.get_field("protected_file_with_view_shared")
    f_restricted = model._meta.get_field("restricted_file_with_view")

    assert f_public.get_view() is None
    v_protected = f_protected.get_view()
    assert f_protected_shared.get_view() == v_protected
    v_restricted = f_restricted.get_view()

    assert v_protected.IS_GENERATED
    assert v_restricted.IS_GENERATED

    assert issubclass(v_protected, ProtectedFileView)
    assert not issubclass(v_protected, RestrictedFileView)
    assert issubclass(v_restricted, RestrictedFileView)

    assert v_protected.DOCUMENT_ROOT == f_protected.storage.location
    assert v_restricted.DOCUMENT_ROOT == f_restricted.storage.location

    assert v_protected.PROTECTED_URLPATHROOT == f_protected.storage.url_root
    assert v_restricted.PROTECTED_URLPATHROOT == f_restricted.storage.url_root

    assert str(v_protected.UPLOAD_TO) == str(f_protected.upload_to)
    assert str(v_restricted.UPLOAD_TO) == str(f_restricted.upload_to)

    assert v_restricted.permission_classes == [
        group_permission("mock_role", "other_mock_role")
    ]


@pytest.mark.parametrize("debug", [True, False])
@pytest.mark.parametrize(
    # matched_path is the `path` that the urlpattern will extract from request_path
    "request_path, matched_path, field, file_exists, x_accel_redirect_url",
    [
        (
            "/test_media/testfile_with_view.txt",
            "testfile_with_view.txt",
            "protected_file_with_view",
            True,
            "/protected/test_protected_2/testfile_with_view.txt",
        ),
        (
            "/test_media/doesntexist.txt",
            "doesntexist.txt",
            "protected_file_with_view",
            False,
            "/protected/test_protected_2/doesntexist.txt",
        ),
    ],
)
@pytest.mark.django_db
@pytest.mark.urls("tests.urls")
def test_view_responses(
    debug,
    request_path,
    matched_path,
    file_exists,
    x_accel_redirect_url,
    field,
    admin_user,
    settings,
    protected_file_field_test_model_factory,
    rf,
):
    test_object = protected_file_field_test_model_factory()
    settings.DEBUG = debug

    request = rf.get(request_path)
    request.user = admin_user

    def _do_request():
        return (
            test_object._meta.get_field(field)
            .get_view()
            .as_view()(request, path=matched_path)
        )

    if not file_exists and debug:
        with pytest.raises(Http404):
            _do_request()
        return

    response = _do_request()
    if debug:
        assert next(response.streaming_content) == b"test_content_3"
        # enough proof, other properties are checked in test_utils
    else:
        assert response["X-Accel-Redirect"] == x_accel_redirect_url


@pytest.mark.django_db
def test_public_file_field_paths(settings, protected_file_field_test_model_factory):
    test_object = protected_file_field_test_model_factory()

    assert test_object.public_file.name.startswith(
        str(Path("test_public_file", "testfile"))
    )
    assert test_object.public_file.path == str(
        Path(mediastorage_settings.PUBLIC_ROOT).absolute() / test_object.public_file.name
    )

    assert test_object.protected_file.name.startswith(
        str(Path("test_protected_1", "testfile"))
    )
    assert test_object.protected_file.path == str(
        Path(settings.MEDIA_ROOT).absolute() / test_object.protected_file.name
    )


@pytest.mark.django_db
def test_url_resolving(
    protected_file_field_test_model_factory, clean_media_dir, set_urlpatterns
):
    test_object = protected_file_field_test_model_factory()
    model = protected_file_field_test_model_factory._meta.model

    set_urlpatterns(
        [protected_file_path("test_media/", model, "protected_file_with_view")]
    )

    # public files always have a view
    assert (
        test_object.public_file.url
        == f"{mediastorage_settings.PUBLIC_URL}{test_object.public_file.name}"
    )

    # doesn't have a view, doesn't have a URL
    assert test_object.protected_file.url is None

    # has a view and a url pattern -> has a url
    assert (
        test_object.protected_file_with_view.url
        == "/test_media/test_protected_2/testfile_with_view.txt"
    )

    # has a view but no url pattern -> no url
    assert test_object.restricted_file_with_view.url is None


@pytest.mark.parametrize("REGISTER_URLPATTERN_MEDIA_URL", [True, False])
@pytest.mark.parametrize("REGISTER_URLPATTERN_PUBLIC_URL", [True, False])
@pytest.mark.parametrize("MEDIASTORAGE_MODE", list(MediaStorageMode))
def test_url_pattern_generation_and_resolution(
    set_urlpatterns,
    settings,
    restore_inventory_afterwards,
    REGISTER_URLPATTERN_MEDIA_URL,
    REGISTER_URLPATTERN_PUBLIC_URL,
    MEDIASTORAGE_MODE,
):
    assert MEDIASTORAGE_MODE in (
        MediaStorageMode.x_accel_redirect,
        MediaStorageMode.http_forward_auth,
    ), f"Error: This test is not implemented for {str(MEDIASTORAGE_MODE)}"

    settings.MEDIASTORAGE = {
        "MODE": MEDIASTORAGE_MODE,
        "REGISTER_URLPATTERN_MEDIA_URL": REGISTER_URLPATTERN_MEDIA_URL,
        "REGISTER_URLPATTERN_PUBLIC_URL": REGISTER_URLPATTERN_PUBLIC_URL,
        "FORWARD_AUTH_ENDPOINT_PATH": "/auth/",
    }
    # need to enable DEBUG mode or URL_PATTERN_PUBLIC_MEDIA_ROOT won't have any effect
    settings.DEBUG = settings.DEBUG or REGISTER_URLPATTERN_PUBLIC_URL
    settings.MEDIA_URL = "/media/"

    class TestModel(models.Model):
        class Meta:
            app_label = "example_app"

        # note: upload_to must match the available field_name parameters
        django_file = models.FileField(upload_to="django_file")
        public_file = PublicFileField(upload_to="public_file")
        protected_file = ProtectedFileField(
            upload_to="protected_file", generate_view=True
        )

    set_urlpatterns(list(build_patterns()))

    # the django_file should only be accessible if URL_PATTERN_GENERAL_MEDIA_ROOT is enabled
    if REGISTER_URLPATTERN_MEDIA_URL:
        file_view, file_view_args, file_view_kwargs = resolve(
            "/media/django_file/test.txt"
        )
        assert file_view.view_class == ProtectedFileView
        assert file_view.view_class.UPLOAD_TO == ""
        assert file_view_kwargs.get("path") == "django_file/test.txt"
    else:
        with pytest.raises(Resolver404):
            resolve("/media/django_file/test.txt")

    # the public file should only be accessible if URL_PATTERN_PUBLIC_MEDIA_ROOT is enabled
    if REGISTER_URLPATTERN_PUBLIC_URL:
        file_view, file_view_args, file_view_kwargs = resolve(
            "/public/public_file/test.txt"
        )
        assert file_view == serve
    else:
        with pytest.raises(Resolver404):
            resolve("/public/public_file/test.txt")

    if MEDIASTORAGE_MODE == MediaStorageMode.http_forward_auth:
        file_view, file_view_args, file_view_kwargs = resolve("/auth/")
        assert file_view.view_class == HTTPForwardAuthView
    else:
        with pytest.raises(Resolver404):
            resolve("/auth/")


@pytest.mark.parametrize(
    "field_kwargs, check_fails",
    [
        ({"view": "django_mediastorage.views.files.ProtectedFileView"}, False),
        (
            {
                "view": "django_mediastorage.views.files.ProtectedFileView",
                "generate_view": True,
            },
            True,
        ),
        (
            {
                "view": "django_mediastorage.views.files.ProtectedFileView",
                "permission_classes": [group_permission("mock_role")],
            },
            True,
        ),
        (
            {
                "protection_class": ProtectionClass.PUBLIC,
                "permission_classes": [group_permission("mock_role")],
            },
            True,
        ),
        ({"generate_view": True}, False),
        (
            {
                "generate_view": True,
                "permission_classes": [group_permission("mock_role")],
            },
            False,
        ),
    ],
)
def test_invalid_field_args_combinations(
    field_kwargs, check_fails, restore_inventory_afterwards
):
    upload_to = f'invalid_combinations+{os.environ.get("PYTEST_CURRENT_TEST")}'

    # TODO: Add more combinations of bad settings here
    # TODO: Also test public file field checks

    class T(models.Model):
        class Meta:
            app_label = "example_app"

        f = ProtectedFileField(upload_to=upload_to, **field_kwargs)

    errors = T.check()

    if check_fails:
        assert len(errors) > 0
    else:
        assert len(errors) == 0
