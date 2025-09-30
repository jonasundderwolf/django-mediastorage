from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Optional, Union

from rest_framework.permissions import BasePermission

from .files import BaseFileView, ProtectedFileView, RestrictedFileView


def cache_generated_view_class(fn: Callable) -> Callable:
    """
    Wrap method in a way that helps with caching of generated views

    This decorator does not actually cache anything, it just compares kwargs with
    a given "other_view" object which might be a candidate. This is meant to be used by
    storage.inventory.
    """

    def wrapper(other_view: type[BaseFileView], **kwargs):
        kwargs_cleaned = {k: v for k, v in kwargs.items() if k != "view_name"}
        if (
            other_view is not None
            and other_view.IS_GENERATED
            and other_view.GENERATED_ARGS == kwargs_cleaned
        ):
            return other_view

        view = fn(**kwargs)
        view.GENERATED_ARGS = kwargs_cleaned
        return view

    wrapper.__name__ = fn.__name__
    wrapper.__qualname__ = fn.__qualname__
    return wrapper


@cache_generated_view_class
def generate_view_class(
    view_name: str,
    is_public: bool,
    upload_to: Union[str, Path],
    document_root: Union[str, Path],
    url_root: str,
    permission_classes: Iterable[type[BasePermission]],
    register_urlpattern: Optional[bool],
) -> type[BaseFileView]:
    assert upload_to

    permission_classes_list = None

    if permission_classes:
        cls = RestrictedFileView
        permission_classes_list = list(permission_classes)
    elif is_public:
        cls = BaseFileView
    else:
        cls = ProtectedFileView

    class GeneratedFileView(cls):
        IS_GENERATED = True
        DOCUMENT_ROOT = document_root
        UPLOAD_TO = upload_to
        PROTECTED_URLPATHROOT = url_root

        if register_urlpattern is not None:
            REGISTER_URLPATTERN = register_urlpattern

        if permission_classes_list:
            permission_classes = permission_classes_list

    GeneratedFileView.__name__ = f"GeneratedFileView({view_name})"
    GeneratedFileView.__qualname__ = f"generate_view_class.{GeneratedFileView.__name__}"

    return GeneratedFileView
