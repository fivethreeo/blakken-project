import base64
import hashlib
import json
import re
import secrets
from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .app_attest import (
    InvalidAppAttest, assertion_client_data_hash, verify_assertion, verify_attestation,
)
from .models import AppAttestChallenge, AppAttestKey
from .native_apps import registration_for_request
from .orders import create_order, ensure_order_channel


REQUEST_HASH_PATTERN = re.compile(r'^[0-9a-f]{64}$')
CHALLENGE_LIFETIME = timedelta(minutes=5)


def _read_json(request):
    if request.content_type != 'application/json' or len(request.body) > 256 * 1024:
        return None
    try:
        value = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _channel_id(request):
    channel = request.session.get('order_channel')
    try:
        return UUID(channel)
    except (TypeError, ValueError):
        return None


@never_cache
@require_POST
def app_attest_challenge(request):
    registration, error = registration_for_request(request, 'ios')
    if error is not None:
        return error
    data = _read_json(request)
    if data is None or set(data) - {'purpose', 'request_hash'}:
        return JsonResponse({'error': 'Invalid challenge request.'}, status=400)
    purpose = data.get('purpose')
    request_hash = data.get('request_hash', '')
    if purpose not in AppAttestChallenge.Purpose.values:
        return JsonResponse({'error': 'Invalid challenge purpose.'}, status=400)
    if purpose == AppAttestChallenge.Purpose.ASSERTION:
        if not isinstance(request_hash, str) or not REQUEST_HASH_PATTERN.fullmatch(request_hash):
            return JsonResponse({'error': 'Invalid request hash.'}, status=400)
    elif request_hash:
        return JsonResponse({'error': 'Unexpected request hash.'}, status=400)

    channel_id = _channel_id(request)
    if channel_id is None:
        ensure_order_channel(request)
        channel_id = _channel_id(request)

    now = timezone.now()
    AppAttestChallenge.objects.filter(expires_at__lte=now).delete()
    active_challenges = AppAttestChallenge.objects.filter(
        customer_channel=channel_id,
        app_registration=registration,
        consumed_at__isnull=True,
        expires_at__gt=now,
    ).count()
    if active_challenges >= 10:
        return JsonResponse({'error': 'Too many active App Attest challenges.'}, status=429)
    challenge = AppAttestChallenge.objects.create(
        customer_channel=channel_id,
        app_registration=registration,
        purpose=purpose,
        challenge=secrets.token_bytes(32),
        request_hash=request_hash,
        expires_at=now + CHALLENGE_LIFETIME,
    )
    return JsonResponse({
        'challenge_id': str(challenge.pk),
        'challenge': base64.b64encode(bytes(challenge.challenge)).decode(),
    })


@never_cache
@require_POST
def attest_app_key(request):
    registration, error = registration_for_request(request, 'ios')
    if error is not None:
        return error
    data = _read_json(request)
    if (data is None or set(data) != {
            'key_id', 'challenge_id', 'attestation_object',
    } or not all(isinstance(data[field], str) for field in data)):
        return JsonResponse({'error': 'Invalid attestation request.'}, status=400)
    try:
        challenge_id = UUID(data['challenge_id'])
        attestation_object = base64.b64decode(data['attestation_object'], validate=True)
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid attestation request.'}, status=400)
    channel_id = _channel_id(request)
    if channel_id is None:
        return JsonResponse({'error': 'Customer session required.'}, status=401)

    try:
        with transaction.atomic():
            challenge = AppAttestChallenge.objects.select_for_update().get(
                pk=challenge_id,
                customer_channel=channel_id,
                app_registration=registration,
                purpose=AppAttestChallenge.Purpose.ATTESTATION,
                consumed_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            result = verify_attestation(
                attestation_object,
                data['key_id'],
                hashlib.sha256(bytes(challenge.challenge)).digest(),
                registration.app_id,
            )
            key, created = AppAttestKey.objects.get_or_create(
                key_id=data['key_id'],
                defaults={
                    'customer_channel': channel_id,
                    'app_registration': registration,
                    'public_key': result.public_key,
                    'app_id': registration.app_id,
                    'bundle_version': result.bundle_version,
                    'validation_category': result.validation_category,
                    'environment': AppAttestKey.Environment.PRODUCTION,
                    'counter': result.counter,
                },
            )
            if not created:
                key = AppAttestKey.objects.select_for_update().get(pk=key.pk)
                if (
                    key.customer_channel != channel_id
                    or key.app_registration_id != registration.pk
                    or key.public_key != result.public_key
                    or key.app_id != registration.app_id
                    or key.environment != AppAttestKey.Environment.PRODUCTION
                ):
                    raise InvalidAppAttest('App Attest key already belongs to another session.')
                key.validation_category = result.validation_category
                key.bundle_version = result.bundle_version
                key.save(update_fields=['validation_category', 'bundle_version'])
            challenge.consumed_at = timezone.now()
            challenge.save(update_fields=['consumed_at'])
    except AppAttestChallenge.DoesNotExist:
        return JsonResponse({'error': 'Invalid or expired challenge.'}, status=401)
    except InvalidAppAttest:
        return JsonResponse({'error': 'App attestation failed.'}, status=401)

    return JsonResponse({'registered': True}, status=201)


@never_cache
@require_POST
def create_attested_order(request, appid, menu_id):
    registration, error = registration_for_request(request, 'ios', 'customer', appid)
    if error is not None:
        return error
    return with_app_attest_proof(
        request,
        registration,
        lambda challenge, request_hash: assertion_client_data_hash(
            challenge, request_hash, appid, menu_id,
        ),
        lambda: create_order(
            request, menu_id, appid, verified_app_registration=registration,
        ),
    )


def with_app_attest_proof(request, registration, hash_for_challenge, action):
    if len(request.body) > 16 * 1024:
        return JsonResponse({'error': 'Payload too large.'}, status=413)

    key_id = request.headers.get('X-App-Attest-Key-ID', '')
    challenge_header = request.headers.get('X-App-Attest-Challenge-ID', '')
    assertion_header = request.headers.get('X-App-Attest-Assertion', '')
    try:
        challenge_id = UUID(challenge_header)
        assertion = base64.b64decode(assertion_header, validate=True)
    except (ValueError, TypeError):
        return JsonResponse({'error': 'App Attest assertion required.'}, status=401)
    channel_id = _channel_id(request)
    if channel_id is None or not key_id:
        return JsonResponse({'error': 'App Attest assertion required.'}, status=401)

    request_hash = hashlib.sha256(request.body).hexdigest()
    try:
        with transaction.atomic():
            challenge = AppAttestChallenge.objects.select_for_update().get(
                pk=challenge_id,
                customer_channel=channel_id,
                app_registration=registration,
                purpose=AppAttestChallenge.Purpose.ASSERTION,
                request_hash=request_hash,
                consumed_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            key = AppAttestKey.objects.select_for_update().get(
                key_id=key_id,
                customer_channel=channel_id,
                app_registration=registration,
                app_id=registration.app_id,
                environment=AppAttestKey.Environment.PRODUCTION,
            )
            client_data_hash = hash_for_challenge(bytes(challenge.challenge), request_hash)
            counter, category, bundle_version = verify_assertion(
                assertion,
                key.public_key,
                key.app_id,
                client_data_hash,
                key.counter,
            )
            key.counter = counter
            key.validation_category = category
            key.bundle_version = bundle_version
            key.save(update_fields=['counter', 'validation_category', 'bundle_version'])
            challenge.consumed_at = timezone.now()
            challenge.save(update_fields=['consumed_at'])
            response = action()
    except (AppAttestChallenge.DoesNotExist, AppAttestKey.DoesNotExist):
        return JsonResponse({'error': 'Invalid or expired App Attest proof.'}, status=401)
    except InvalidAppAttest:
        return JsonResponse({'error': 'App Attest verification failed.'}, status=401)
    return response
