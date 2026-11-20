from django.utils.deprecation import MiddlewareMixin

from .tokens import user_from_access_token


class JWTAuthenticationMiddleware(MiddlewareMixin):
    def process_request(self, request):
        authorization = request.headers.get('Authorization', '')
        scheme, _, token = authorization.partition(' ')
        if scheme.lower() == 'bearer' and token:
            user = user_from_access_token(token)
            if user is not None:
                request.user = user
