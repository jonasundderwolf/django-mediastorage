# django-mediastorage
> **ℹ️ Project Status: Alpha**
>
> The library is **functionally stable**, but still in **alpha** due to ongoing development.
> Interfaces may change and not all edge cases are covered yet.

A library that allows to protect media files that are served via nginx or traefik to be authenticated

## Overview

It is recommended that in production settings media files are served by a web server
(nginx, traefik, Apache, ...). However, there is no unified way to authorize user access
to files on these web servers, and this library fills this gap.

We assume that there is a reverse proxy that directs some requests to django, and serves
media files either directly, or directs these requests to another service.

### nginx

Nginx uses X-Accel-Redirect. Take a look at this nginx configuration:
```nginx configuration
location /media {
  proxy_pass http://django-upstream;
}

location /protected_media {
  root /data/media;
  internal;
}
```

The `/media` path, which is exposed to users, will be forwarded to Django. When using this
library, Django will not respond with a file, but instead respond with an empty "200 OK"
response, which has a special header set: `X-Accel-Redirect: /protected_media/path/to/file`.
Nginx recognises this header, and will internally redirect the Request to the respective
path, and then handle it in whatever way the location is set up (in this case, it will
just serve the file from the media directory). Because of the `internal;` setting on this
location, it is not allowed for any client to request data in this location directly—It is
possible only with internal redirects using `X-Accel-Redirect` to access it.

### traefik

Traefik does not serve files directly. In our scenario, there is a django backend running
on one endpoint, and an nginx/apache/etc web server running on another endpoint. Traefik
will forward requests for static files or media files to the web server, and all other
requests to Django:
```yaml
services:
  django:
    labels:
      traefik.http.router.django.rule: "PathPrefix(`/`)"
  nginx:
    labels:
      traefik.http.router.nginx_static.rule: "PathPrefix(`/static`) || PathPrefix(`/public`)"
      traefik.http.router.nginx_media.rule: "PathPrefix(`/media`)"
      traefik.http.middlewares.nginx_media.forwardAuth.address: "http://django/auth/"
```

We have configured traefik's HTTP Forward Auth middleware to be applied to requests to
media files. When a user sends a request for a file in the `/media` path, traefik will
first send a Request to django's `/auth` endpoint, where the original path is transmitted
in the HTTP Header `X-Forwarded-Uri`, and most other headers (like Basic Auth or Cookies)
will be included in this request. When Django responds with any 2XX status code, the
request will be forwarded to the nginx container. When Django responds with a 3XX, 4XX, or
5XX status code, traefik will send Django's response back to the user instead.

Normally, no request to `/media` should ever be forwarded directly to Django in this mode.

## Configuration

django-mediastorage is configured in Django settings:
```python
MEDIASTORAGE = {
    "MODE": 'x-accel-redirect',
    "ENABLE_INVENTORY_CHECKS": True,  # (deprecated, will be removed)
    "REGISTER_URLPATTERN_MEDIA_URL": False,
    "REGISTER_URLPATTERN_PUBLIC_URL": True,
    "PUBLIC_ROOT": os.path.join(MEDIA_ROOT, 'public'), 
    "PUBLIC_URL": '/public/',
    "FORWARD_AUTH_ENDPOINT_PATH": '/auth/',
    "FILESERVER_MEDIA_URL": None,
}
```

### Mode
`MODE` can be `x-accel-redirect` (made for nginx) or `http-forward-auth` (made for 
traefik). See the overview section above for details on how these work. The mode should be
set to work with the current reverse proxy.

### URL Patterns
django-mediastorage can automatically generate all required URL patterns. In addition to
that, it offers a few extra patterns to make life easier:

- `REGISTER_URLPATTERN_MEDIA_URL`: When set to true, a URL pattern that serves
  all files in the `MEDIA_ROOT` is generated. This acts like a fallback for media files 
  that are not managed by django-mediastorage. Requests to these files will be allowed for
  all active, authenticated users.
- `REGISTER_URLPATTERN_PUBLIC_URL`: See the section 
  ["The Public Path"](the-public-path) for details. When set to true, a `serve_static`
  view for the public path will be present when `DEBUG=True`.

### The Public Path
Some media files are public and don't need special authentication. You can use the public
path for this purpose. These files can be served directly by nginx.

- `PUBLIC_ROOT`: Similar to `MEDIA_ROOT`, the directory where publically available media
  files are stored. This must be a subdirecotry of `MEDIA_ROOT`. FileFields that upload to
  this directory will not have the restrictions imposed on other FileFields regarding
  sharing directories. Can be set to None to default to `$MEDIA_ROOT/public`
- `PUBLIC_URL`: URL Prefix that this will be available at. This won't be a sub-path of
  `MEDIA_URL` so that it's easier to match in the reverse proxy.

Note: When using `REGISTER_URLPATTERN_MEDIA_URL`, public files will be available at the
respective subdirectory of http://django/$MEDIA_URL in addition to their intended public
URL at http://django/$PUBLIC_URL.

### Fileserver integration

- `FORWARD_AUTH_ENDPOINT_PATH`: Only used in `http-forward-auth` mode. This is the Path
  of the HTTP Forward Auth endpoint that the reverse proxy can use.
- `FILESERVER_MEDIA_URL`: Path prefix for media files on the web server.
  - When running in `x-accel-redirect` mode, this should match the `internal` location 
    from your nginx config. `MEDIA_URL` and `FILESERVER_MEDIA_URL` should have the same
    structure for all files inside it (i.e., `/$MEDIA_URL/path/to/file.txt` and 
    `/$FILESERVER_MEDIA_URL/path/to/file.txt` should correspond to the same file), but 
    they must be different paths.
  - When running in `http-forward-auth` mode, this should be the same as `MEDIA_URL`. It
    defaults to `MEDIA_URL` so there is no need to set it. This is used in a few edge
    cases where a request for a FileView may be forwarded to Django.

# Old docs (need to be re-worked)

## Quick-Start

### Files That Should be Available Publicly

Use `PublicFileFiled` or `PublicImageField` the same way you would use the normal
FileFields. It'll accept the same arguments as the normal fields.

```python
from django.db import models
from django_mediastorage.fields import PublicFileField

class Example(models.Model):
    example_file = PublicFileField(upload_to="unique_upload_to_path")
```

The files will be available at the `/public` URL path.

Make sure that the upload_to path is unique to all `ProtectedFileField` and
`PublicFileField` instances.

### Files That Should Only be Served to Authenticated and Active Users

Instead of `FileField` or `ImageField`, use `ProtectedFileField` or `ProtectedImageField`.
These accept the same fields as the normal FileFields, and some special arguments.

You will need to give some information on the protection class of the file (i.e., the kind
of care we need to take handling the file). You can read about the individual choices in
the enum itself: `django_mediastorage.constants.ProtectionClass`. Note that when using
`ProtectionClass.PUBLIC`, you are essentially creating a `PublicFileField` (in fact,
`PublicFileField` is a `ProtectedFileField` with defaults that are suited for public
files).

If you just want the file to be available in the `/media` subpath, all you need to do is
add the `generate_view=True` argument:

```python
from django.db import models

from django_mediastorage.fields import ProtectedFileField
from django_mediastorage.constants import ProtectionClass

class Example(models.Model):
    example_file = ProtectedFileField(
        generate_view=True,
        protection_class=ProtectionClass.INTERNAL,
        upload_to="unique_upload_to_path",
    )
```

If you want to restrict access to the files, the easiest way to do this is to also specify
`permission_classes`, which work the same way as you would set the permission classes for
a `rest_framework.view.APIView`:

```python
from django.db import models

from django_mediastorage.fields import ProtectedFileField
from django_mediastorage.constants import ProtectionClass

from your_project.your_app.auth import ExampleRestFrameworkPermission

class Example(models.Model):
    example_file = ProtectedFileField(
        generate_view=True,
        permission_classes=[ExampleRestFrameworkPermission],
        protection_class=ProtectionClass.PRIVATE,
        upload_to="unique_upload_to_path",
    )
```

In the future, we will also support django's built-in permission model.

That's all you need to know to start. But there are some advanced features you can also
use.

Make sure that the upload_to path is unique to all `ProtectedFileField` and
`PublicFileField` instances.

## Understanding What's Happening

The two classes serve three purposes, which we will discuss here

### The Inventory

All `ProtectedFileField` and `PublicFileFiled` instances are registered to an inventory.

This inventory is used to build the URL patterns for the media directory.

It also helps us keeping track of what kind of files are in which directory, which is
useful for the operation of the software.

The inventory also helps us avoiding mixing different kinds of files into the same
directory.

### Individual Views per Directory

Each upload_to directory has its own view. This has the benefit of allowing to use
different permission settings for each individual FileField, as well as some advanced
features like custom URL patterns, custom access control functions, or other custom code
that can be run before serving the file (e.g., ad-hoc generation of a PDF file).

With the `generate_view=True` argument, the file storage can automatically generate a view
for each `ProtectedFileField` or `PublicFileField`. However, you can define your own view
instead if you wish so.

### Access Restriction and Reverse Proxy Integration

As discussed earlier, the file storage uses some general code for restricting access
to files.

It also provides views that serve files in a `DEBUG` environment, while providing
X-Accel-Redirect forwarding in non-`DEBUG` environments (i.e., speeding up serving
of the file when running behind a reverse proxy)

## ProtectedFileField Reference

### Behavior

When using ProtectedFileFields, an inventory of all used paths will be created during
import of the models. The inventory also checks for conflicts and will raise a
`ValueError` if any violation is found.

Every `ProtectedFileField` is associated with a view. The view can be auto-generated and
automatically registered to `urls.py`, so no more manual intervention is necessary for the
default use case.

### Arguments

In addition to the arguments of `FileField` and `ImageField`, the `ProtectedFileField`
and `ProtectedImageField` classes take the following arguments:

### `upload_to` (mandatory)

Although this is also used by FileField, this should be noted here as well, as this is the
basis for the Inventory to function.

All files are indexed by their `upload_to` directory. Note that the actual storage root is
ignored when indexing – this is because the storage's document root may change due to
settings, which may lead to issues during setup.

Two ProtectedFileFields may only share the `upload_to` path when they are from the same
model. Furthermore, they must use the same view (when generating views, this scenario is
automatically detected, and only one view is generated for both fields. Keep in mind that
this is only possible when using the same view-related arguments for both fields).

Passing functions to `upload_to` is not yet supported (if you need support for this, open
a ticket). When passing strftime formatting (e.g., `documents/%Y`), only the static part
at the beginning of the path will be used for indexing (in this case, `documents/`).

### `protection_class` (mandatory)

Must be a value of `django_mediastorage.constants.ProtectionClass`, or a string
representation of it. Defines the protection class of the associated file. Mostly an
annotation without any influence on the program, except that when using
`ProtectionClass.PUBLIC`, the file uses a different storage.

### `view` (optional)

Can be a string, or a View class. The view that is to be
associated with the FileField. This is used for the generation of URL patterns as well as
reverse lookups for getting the URL for a given file.

If no view is associated with a ProtectedFileField, neither reverse lookups nor URL
pattern generation will work for the files stored by this field.

Cannot be used in combination with `generate_view`, because only one view can be directly
associated with a ProtectedFileField.

When providing a string, it should be the fully qualified class name, e.g.,
`your_project.your_app.views.PdfAttachmentView`. Providing a string is meant as a
workaround for cases where the actual class cannot be provided due to circular imports. 
The view will be imported at some point in the future.

### `generate_view` (optional)

Set to `True` to automatically generate a view for the FileField, instead of providing one
via the `view` argument.

Cannot be used in combination with `view`.

Depending on whether the file is supposed to be public, and whether `permission_classes`
is set, it uses a different subclass

### `permission_classes` (optional)

Can only be used when `generate_view=True`. Supply some
[`BasePermission`](https://www.django-rest-framework.org/api-guide/permissions/) classes to be applied when accessing the view.

### `register_generated_view_in_general_media_path` (optional)

Can only be used when `generate_view=True`. When set to `True`, do not automatically
generate a URL pattern in `django_mediastorage.url.build_patterns()`.

This is meant to be set when using `django_mediastorage.urls.protected_file_path` for the
field instead, of when setting a custom URL pattern.

### PublicFileField

Although not a direct subclass, `PublicFileField` behaves like a subclass of
`ProtectedFileField`. The protection class is always PUBLIC and no view is associated
with it. However, it uses a different storage and FieldFile subclass, so that reverse URL
lookup is working here.

## Writing Your own Views or URL patterns

### Writing Your Own Views

If you need any modifications to how the views work, you can create a subclass of the
views. If you do so, you'll likely want to pass the view class to a ProtectedFileView's
`view` argument, and also create a URL pattern for it.

All relevant views are defined in `django_mediastorage.views.files`.

As base class, use `BaseFileView` if you want to implement permission settings on your
own, use `ProtectedFileView` if you want only authorized active users to access the files,
or `RestrictedFileView` to also apply role restrictions. Note that you can always add more
specialized authorization code on top of the existing restrictions.

The documentation (docstrings) of those classes should help you get everything done.

### Creating URL Patterns

There are multiple ways to create URL patterns for ProtectedFileFields and their views.

- The inventory can create a list of URLPatterns for all ProtectedFileFields with
  views where this feature is not explicitly disabled:

  ```python
  from django_mediastorage.urls import build_patterns

  urlpatterns += build_patterns()
  ```

- You can use the `ProtectedFileField.url_pattern()` method. There's a shorthand available
  at `django_mediastorage.urls.protected_file_path`:

  ```python
  from django_mediastorage.urls import protected_file_path
  from my_project.my_app.models import ExampleModel

  urlpatterns += [protected_file_path('url/root/path/', ExampleModel, 'example_file_field')]
  ```

- Register your own URLPattern as you like. Make sure the pattern provides the necessary
  variables needed by `BaseFileView._get_path`. By default, this is the path of
  the file relative to the `upload_to` directory.
