import tempfile

import factory
import pytest
from django.apps import apps
from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import connection, models
from django.urls import get_resolver
from pytest_factoryboy import register

from django_mediastorage.constants import ProtectionClass
from django_mediastorage.fields import ProtectedFileField, PublicFileField
from django_mediastorage.storage import inventory

from .utils import group_permission


@pytest.fixture
def restore_inventory_afterwards():
    """
    All changes to the inventory done during the test will be undone afterwards.
    """
    current_records = inventory._file_inventory._entries.copy()
    yield
    inventory._file_inventory._entries = current_records


@pytest.fixture
@pytest.mark.urls("tests.urls")
def set_urlpatterns():
    """
    Allows changing url patterns during the test, in a way that these changes will be
    undone afterwards
    """
    url_resolver = get_resolver()
    url_patterns_before = url_resolver.urlconf_module.urlpatterns

    def fn(urlpatterns: list):
        url_resolver.urlconf_module.urlpatterns = urlpatterns
        try:
            del url_resolver.url_patterns
        except AttributeError:
            pass
        try:
            del url_resolver.reverse_dict
        except AttributeError:
            pass

    yield fn

    # restore url patterns from before
    fn(url_patterns_before)


@pytest.fixture
@pytest.mark.django_db
def protected_file_field_test_model_factory(example_app, restore_inventory_afterwards):
    class ProtectedFileFieldTestModel(models.Model):
        class Meta:
            app_label = "example_app"

        public_file = PublicFileField(upload_to="test_public_file")
        protected_file = ProtectedFileField(upload_to="test_protected_1")
        much_more_protected_file = ProtectedFileField(
            upload_to="test_protected_1", protection_class=ProtectionClass.CONFIDENTIAL
        )

        public_file_with_view = PublicFileField(
            upload_to="test_public_2", generate_view=True
        )
        protected_file_with_view = ProtectedFileField(
            upload_to="test_protected_2", generate_view=True
        )
        protected_file_with_view_shared = ProtectedFileField(
            upload_to="test_protected_2", generate_view=True
        )
        restricted_file_with_view = ProtectedFileField(
            upload_to="test_protected_3",
            generate_view=True,
            permission_classes=[group_permission("mock_role", "other_mock_role")],
        )

        restricted_file_with_view_1 = ProtectedFileField(
            upload_to="test_protected_4",
            generate_view=True,
            permission_classes=[group_permission("mock_role")],
        )
        restricted_file_with_view_2 = ProtectedFileField(
            upload_to="test_protected_5",
            generate_view=True,
            permission_classes=[group_permission("other_role")],
        )
        restricted_file_with_view_3 = ProtectedFileField(
            upload_to="test_protected_6",
            generate_view=True,
            permission_classes=[
                group_permission("mock_role"),
                group_permission("other_role"),
            ],
        )

    example_app.migrate()

    @register
    class ProtectedFileFieldTestModelFactory(factory.django.DjangoModelFactory):
        class Meta:
            model = ProtectedFileFieldTestModel

        public_file = factory.django.FileField(
            filename="testfile.txt", data="test_content"
        )
        protected_file = factory.django.FileField(
            filename="testfile.txt", data="test_content"
        )
        protected_file_with_view = factory.django.FileField(
            filename="testfile_with_view.txt", data="test_content_3"
        )
        restricted_file_with_view = factory.django.FileField(
            filename="testfile_with_view.txt"
        )

        restricted_file_with_view_1 = factory.django.FileField(filename="testfile1.txt")
        restricted_file_with_view_2 = factory.django.FileField(filename="testfile2.txt")
        restricted_file_with_view_3 = factory.django.FileField(filename="testfile3.txt")

    yield ProtectedFileFieldTestModelFactory


@pytest.fixture(scope="session")
def django_db_setup(django_db_blocker):
    # we need to do a bit of a workaround here, see
    # https://github.com/pytest-dev/pytest-django/issues/643#issuecomment-2379919415
    # for details.

    from django.conf import settings
    from django.db import connections

    from .django_settings import DATABASES

    del connections.__dict__["settings"]

    settings.DATABASES = DATABASES

    # re-configure the settings given the changed database config
    connections._settings = connections.configure_settings(settings.DATABASES)
    # open a connection to the database with the new database config
    connections["default"] = connections.create_connection("default")

    # also need to do the migrations
    with django_db_blocker.unblock():
        call_command("migrate", run_syncdb=True)
        connection.disable_constraint_checking()


@pytest.fixture
def clean_media_dir(settings):
    """
    ensure that a clean media root is set.
    internally, this will update settings.MEDIA_ROOT to a tempfile.TemporaryDirectory().
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        settings.MEDIA_ROOT = tmpdir
        yield


@pytest.fixture
def example_app(settings, restore_inventory_afterwards):
    """
    Install an example Django app that exposes a method to migrate the database.

    This fixture allows to define models directly in a test function. Call
    example_app.migrate() to migrate the database after models have been defined or
    redefined.
    """
    settings.INSTALLED_APPS += ("tests.example_app",)

    # Clear Django’s model registry for the example app to suppress a RuntimeError that
    # complains about conflicting model definitions. The error’s purpose is to prevent
    # the definition of multiple models with the same name for the same app. For the
    # purpose of this fixture, however, it is explicitly desired that several tests can
    # define models with the same name, because in any case only the models defined in the
    # respective test are applied.
    apps.all_models["example_app"].clear()

    class ExampleApp:
        def migrate(self):
            call_command("migrate", run_syncdb=True)

    yield ExampleApp()
    ContentType.objects.clear_cache()


@register
class UserFactory(factory.django.DjangoModelFactory):
    """
    Build sample user instances for testing purposes.

    Class attributes
    ----------------
    base_roles
        A list of role keys that will be added to all generated user instances without
        explicit specification. The list is empty by default and can be overwritten by
        subclassing factories.
    """

    email = factory.Sequence(lambda n: f"user-{n}@example.com")
    username = factory.Sequence(lambda n: f"username{n}")
    first_name = factory.Sequence(lambda n: f"FirstName{n}")
    last_name = factory.Sequence(lambda n: f"LastName{n}")
    is_active = True

    class Meta:
        model = User
        django_get_or_create = ("username",)

    @factory.post_generation
    def groups(obj, create, roles_to_add, **kwargs):
        if not create or not roles_to_add:
            return
        groups = []
        for role in roles_to_add:
            if isinstance(role, Permission):
                groups.append(role)
            else:
                groups.append(Group.objects.get_or_create(name=role)[0])
        obj.groups.add(*groups)
        return groups
