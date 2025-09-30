import sys
from collections import defaultdict
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Callable, Iterable

from django.conf import settings as django_settings
from django.core import checks

from django_mediastorage.constants import MediaStorageMode

if TYPE_CHECKING:
    __all__ = [
        "MODE",  # noqa: F822
        "FORWARD_AUTH_ENDPOINT_PATH",  # noqa: F822
        "ENABLE_INVENTORY_CHECKS",  # noqa: F822
        "REGISTER_URLPATTERN_MEDIA_URL",  # noqa: F822
        "REGISTER_URLPATTERN_PUBLIC_URL",  # noqa: F822
        "PUBLIC_URL",  # noqa: F822
        "FILESERVER_MEDIA_URL",  # noqa: F822
        "PUBLIC_ROOT",  # noqa: F822
    ]


class MediaStorageSettings(ModuleType):
    """
    Custom settings class, that can handle default settings:
    - check if accessed attribute is in default settings. if not, return AttributeError
    - check if attribute is defined in settings.MEDIASTORAGE
      - if yes, select this setting
      - if no, select the default setting
    - if a transformation function for the selected value is defined in
      _django_settings_transformations, apply this transformation
    - return the resulting value.

    All other settings can be defined as properties.
    """

    _default_settings = {
        "MODE": None,
        "FORWARD_AUTH_ENDPOINT_PATH": "/auth/",
        "ENABLE_INVENTORY_CHECKS": True,
        "REGISTER_URLPATTERN_MEDIA_URL": False,
        "REGISTER_URLPATTERN_PUBLIC_URL": True,
        "PUBLIC_ROOT": None,
        "PUBLIC_URL": "/public/",
        "FILESERVER_MEDIA_URL": None,
    }
    _django_settings_transformations: dict[str, Callable] = defaultdict(
        # if a value is not specified, default to the identity function
        lambda: lambda x: x,
        {"MODE": MediaStorageMode},
    )

    def __getattr__(self, item):
        """
        implement behaviour described in class doc
        """
        if item == "PUBLIC_ROOT":
            if (
                django_value := django_settings.MEDIASTORAGE.get("PUBLIC_ROOT")
                is not None
            ):
                return Path(django_value)
            return Path(django_settings.MEDIA_ROOT) / "public"

        if item == "FILESERVER_MEDIA_URL":
            if django_value := django_settings.MEDIASTORAGE.get("FILESERVER_MEDIA_URL"):
                return django_value
            match self.MODE:
                case MediaStorageMode.x_accel_redirect:
                    return None
                case MediaStorageMode.http_forward_auth:
                    return django_settings.MEDIA_URL

        if item in self._default_settings.keys():
            return self._django_settings_transformations[item](
                django_settings.MEDIASTORAGE.get(item, self._default_settings[item])
            )

        return super().__getattribute__(item)

    def __dir__(self) -> list[str]:
        return (
            list(self._default_settings.keys())
            + list(super().__dir__())
            + ["PUBLIC_ROOT"]
        )

    def _check_settings_http_forward_auth(self) -> Iterable[checks.CheckMessage]:
        if django_settings.MEDIA_URL != self.FILESERVER_MEDIA_URL:
            yield checks.Warning(
                "When running in `http_forward_auth` mode, FILESERVER_MEDIA_URL should match MEDIA_URL",
                hint='Unset settings.MEDIASTORAGE["FILESERVER_MEDIA_URL"], then it will default to MEDIA_URL',
                obj=self,
                id="django_mediastorage.Settings.W001",
            )

    def _check_settings_x_accel_redirect(self):
        if self.FILESERVER_MEDIA_URL is None:
            yield checks.Warning(
                "FILESERVER_MEDIA_URL must not be None",
                hint='Set settings.MEDIASTORAGE["FILESERVER_MEDIA_URL"] to match the '
                "internal location from your nginx config",
                obj=self,
                id="django_mediastorage.Settings.E002",
            )
        if django_settings.MEDIA_URL == self.FILESERVER_MEDIA_URL:
            yield checks.Warning(
                "MEDIA_URL and FILESERVER_MEDIA_URL should be different",
                hint="Double-check these settings with your nginx config. "
                "MEDIA_URL should be a location that nginx will forward to django. "
                "FILESERVER_MEDIA_URL should be a location that is marked as `internal;` "
                "and served from a directory",
                obj=self,
                id="django_mediastorage.Settings.W002",
            )

    # todo: test these checks
    def check_settings(self, **kwargs) -> Iterable[checks.CheckMessage]:
        if "MODE" not in django_settings.MEDIASTORAGE:
            yield checks.Error(
                "django_mediastorage MODE must be defined",
                hint="Set MEDIASTORAGE['MODE']",
                obj=self,
                id="django_mediastorage.Settings.E001",
            )
        if django_settings.MEDIASTORAGE["MODE"] not in MediaStorageMode:
            yield checks.Error(
                f"django_mediastorage MODE must be one of {', '.join(str(m) for m in MediaStorageMode)}",
                hint="Set MEDIASTORAGE['MODE'] to one of these values",
                obj=self,
                id="django_mediastorage.Settings.E002",
            )

        if not self.ENABLE_INVENTORY_CHECKS:
            yield checks.Error(
                "ENABLE_INVENTORY_CHECKS should not be disabled outside of testing",
                hint='Unset settings.MEDIASTORAGE["ENABLE_INVENTORY_CHECKS"]',
                obj=self,
                id="django_mediastorage.Inventory.E201",
            )

        if not self.PUBLIC_ROOT.is_relative_to(django_settings.MEDIA_ROOT):
            yield checks.Error(
                "PUBLIC_ROOT must be a subdirectory or MEDIA_ROOT",
                hint='update settings.MEDIASTORAGE["PUBLIC_ROOT"] to be a subdirectory of'
                "settings.MEDIA_ROOT",
                obj=self,
                id="django_mediastorage.Settings.E004",
            )

        for key, value in self._default_settings.items():
            if value is None:
                continue
            if django_settings.MEDIASTORAGE.get(key, value) is not None:
                continue
            yield checks.Error(
                f"settings.MEDIASTORAGE['{key}'] must not be None",
                hint=f"Unset settings.MEDIASTORAGE['{key}'] to get the default"
                f"behaviour, or set it to an actual value.",
                obj=self,
                id="django_mediastorage.Settings.E003",
            )

        if self.MODE == MediaStorageMode.http_forward_auth:
            yield from self._check_settings_http_forward_auth()
        elif self.MODE == MediaStorageMode.x_accel_redirect:
            yield from self._check_settings_x_accel_redirect()


# see https://docs.python.org/3/reference/datamodel.html#customizing-module-attribute-access
sys.modules[__name__].__class__ = MediaStorageSettings
