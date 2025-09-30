from rest_framework.permissions import BasePermission


class BaseHasRolePermission(BasePermission):
    """
    Class to use as superclass for the role_permission function.

    This has the advantage of allowing to use `instanceof`
    """

    pass


_group_permissions_cache = {}


def group_permission(*groups):
    """
    Generate permissions based on roles. Rather try to use django model permissions.

    Using this method means defining again a list of roles, which can then be in conflict
    with the admin models permissions defined in roles.conf.
    In most cases you probably want to use ViewOnlyWithEditPermissionsModelPermissions
    instead of this function.

    The two uses cases for this function are:
    1. The frontend/api definitions need to be different than the ones for admin. This
       is highly error-prone and should be avoided, but might be required.
    2. There are no permissions set in the roles.conf for the specific model, i.e.
       when the admin is disabled on purpose for one model.
    """
    groups_str = ",".join(sorted(groups))

    if groups_str in _group_permissions_cache:
        return _group_permissions_cache[groups_str]

    class HasGroupPermission(BaseHasRolePermission):
        def has_permission(self, request, view):
            return request.user.groups.filter(name__in=groups).exists()

        def has_object_permission(self, request, view, obj):
            return self.has_permission(request, view)

    HasGroupPermission.__name__ += f'({",".join(groups)})'
    HasGroupPermission.__qualname__ += f'({",".join(groups)})'

    _group_permissions_cache[groups_str] = HasGroupPermission
    return HasGroupPermission
