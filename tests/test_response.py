import os
from pathlib import Path

import pytest
from django.http import Http404

from django_mediastorage.response import HttpResponseXAccelRedirect, build_file_response

# todo: split this file into utils and x_accel_redirect.
# todo: also test build_file_response for x_accel_redirect mode.


@pytest.mark.parametrize("redirect_target", ["http://example.com/test", "/test/hello"])
def test_http_response_x_accel_redirect(redirect_target):
    response = HttpResponseXAccelRedirect(redirect_target)
    assert not response.content
    assert response["content-type"] == ""
    assert response.headers["X-Accel-Redirect"] == redirect_target


@pytest.mark.parametrize(
    "redirect_target, escape_map",
    [
        ("/über", {"ü": "%C3%BC"}),
        ("/test with special chars < =", {" ": "%20", "<": "%3C", "=": "%3D"}),
        (
            "emoji!🏳️‍🌈♥",
            {"♥": "%E2%99%A5", "🏳️‍🌈": "%F0%9F%8F%B3%EF%B8%8F%E2%80%8D%F0%9F%8C%88"},
        ),
    ],
)
def test_http_response_x_accel_redirect_escape(redirect_target, escape_map):
    response = HttpResponseXAccelRedirect(redirect_target)
    response_target = response["X-Accel-Redirect"]
    target_replaced = redirect_target
    for c, escape in escape_map.items():
        assert c not in response_target
        assert escape in response_target
        target_replaced = target_replaced.replace(c, escape)
    assert target_replaced == response_target

    def test_build_file_response__production__success(settings, rf):
        testfile = "testfile_core_filestorage__ps.txt"
        testfile_full = Path(settings.MEDIA_ROOT, testfile)
        protected_path = "/protected/"

        settings.DEBUG = False

        request = rf.get(f"/{testfile}")

        os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
        with open(testfile_full, "w+") as f:
            f.write("test_content")

        response = build_file_response(
            request, testfile, settings.MEDIA_ROOT, protected_path
        )

        assert response["X-Accel-Redirect"] == f"{protected_path}{testfile}"
        assert response["Content-Type"] == ""


def test_build_file_response__production__doesntexist(settings, rf):
    testfile = "testfile_core_filestorage__pd.txt"
    testfile_full = Path(settings.MEDIA_ROOT, testfile)
    protected_path = "/protected/"

    settings.DEBUG = False

    request = rf.get(f"/{testfile}")

    if testfile_full.exists():
        os.remove(testfile_full)

    response = build_file_response(request, testfile, settings.MEDIA_ROOT, protected_path)

    assert response["X-Accel-Redirect"] == f"{protected_path}{testfile}"
    assert response["Content-Type"] == ""


def test_build_file_response__debug__success(settings, rf):
    testfile = "testfile_core_filestorage__ds.txt"
    testfile_full = Path(settings.MEDIA_ROOT, testfile)
    protected_path = "/protected/"

    settings.DEBUG = True

    request = rf.get(f"/{testfile}")

    os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
    with open(testfile_full, "w+") as f:
        f.write("test_content")

    response = build_file_response(request, testfile, settings.MEDIA_ROOT, protected_path)

    assert response.status_code == 200
    assert next(response.streaming_content) == b"test_content"
    assert response["Content-Type"] == "text/plain"


def test_build_file_response__debug__doesntexist(settings, rf):
    testfile = "testfile_core_filestorage__dd.txt"
    testfile_full = Path(settings.MEDIA_ROOT, testfile)
    protected_path = "/protected/"

    settings.DEBUG = True

    request = rf.get(f"/{testfile}")

    if testfile_full.exists():
        os.remove(testfile_full)

    with pytest.raises(Http404):
        build_file_response(request, testfile, settings.MEDIA_ROOT, protected_path)
