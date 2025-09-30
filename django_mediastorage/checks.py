from typing import Iterable

from django.core import checks


@checks.register
def check_settings(**kwargs) -> Iterable[checks.CheckMessage]:
    from . import settings

    yield from settings.check_settings(**kwargs)
