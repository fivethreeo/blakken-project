import base64

from django.http import Http404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .api import obtain_tokens, refresh_tokens
from .app_attest_views import with_app_attest_proof
from .native_apps import management_client_data_hash, registration_for_request
from .play_integrity_views import with_play_integrity_proof


@never_cache
@require_POST
def management_attested_auth(request, platform, operation):
    if platform not in ('ios', 'android') or operation not in ('token', 'refresh'):
        raise Http404
    registration, error = registration_for_request(request, platform, 'management')
    if error is not None:
        return error

    def request_hash(challenge, body_hash):
        digest = management_client_data_hash(
            challenge, bytes.fromhex(body_hash), registration.pk, operation,
        )
        return digest if platform == 'ios' else base64.urlsafe_b64encode(digest).decode().rstrip('=')

    def authenticate():
        request.verified_app_registration = registration
        return obtain_tokens(request) if operation == 'token' else refresh_tokens(request)

    verify = with_app_attest_proof if platform == 'ios' else with_play_integrity_proof
    return verify(request, registration, request_hash, authenticate)
