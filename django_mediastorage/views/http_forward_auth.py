from django.http import HttpResponse, HttpResponseForbidden
from django.urls import resolve
from django.views import View


class HTTPForwardAuthView(View):
    """
    A view that implements the HTTP Forward Auth endpoint, as described in
    https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/forwardauth/

    The current request should have gone through all the middlewares that would attach
    information like the current user (based on HTTP headers) and other checks.

    This view uses Django's default URL Resolver to find the BaseFileView for the path
    given in the current request's `X-Forwarded-Uri` header.

    It'll then set up the view and call `check_access()` on it to check if the current
    user has access to this file.

    It returns an empty status 200 http response if the user has access, or an
    HttpResponseForbidden otherwise. Note that this response will follow back all the
    middlewares, and the result of that will likely be exposed to the user.
    """

    def get(self, request, **kwargs):
        original_path = request.headers.get("X-Forwarded-Uri")

        file_view, file_view_args, file_view_kwargs = resolve(original_path)

        file_view_obj = file_view.view_class()
        request.path = original_path
        file_view_obj.setup(request, *file_view_args, **file_view_kwargs)

        if not file_view_obj.check_access():
            return HttpResponseForbidden()
        else:
            return HttpResponse("", status=200)
