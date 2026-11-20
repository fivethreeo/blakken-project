from datetime import timedelta
from uuid import uuid4

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import RefreshToken


class InvalidToken(Exception):
    pass


def _encode(user, token_type, jti, lifetime, app_registration=None):
    now = timezone.now()
    return jwt.encode({
        'sub': str(user.pk),
        'type': token_type,
        'jti': str(jti),
        'iat': now,
        'exp': now + lifetime,
        **({'app_registration': str(app_registration.pk)} if app_registration else {}),
    }, settings.JWT_SIGNING_KEY, algorithm='HS256')


def issue_token_pair(user, app_registration=None):
    jti = uuid4()
    expires_at = timezone.now() + timedelta(seconds=settings.JWT_REFRESH_TTL_SECONDS)
    RefreshToken.objects.create(
        jti=jti, user=user, expires_at=expires_at, app_registration=app_registration,
    )
    return {
        'access': _encode(
            user, 'access', uuid4(),
            timedelta(seconds=settings.JWT_ACCESS_TTL_SECONDS),
            app_registration,
        ),
        'refresh': _encode(
            user, 'refresh', jti, timedelta(seconds=settings.JWT_REFRESH_TTL_SECONDS),
            app_registration,
        ),
        'access_expires_in': settings.JWT_ACCESS_TTL_SECONDS,
        'refresh_expires_in': settings.JWT_REFRESH_TTL_SECONDS,
    }


def decode_token(raw_token, expected_type):
    try:
        payload = jwt.decode(
            raw_token,
            settings.JWT_SIGNING_KEY,
            algorithms=['HS256'],
            options={'require': ['sub', 'type', 'jti', 'iat', 'exp']},
        )
    except (jwt.InvalidTokenError, TypeError, ValueError) as error:
        raise InvalidToken from error
    if payload.get('type') != expected_type:
        raise InvalidToken
    return payload


def user_from_access_token(raw_token):
    try:
        payload = decode_token(raw_token, 'access')
        user = get_user_model()._default_manager.get(pk=payload['sub'], is_active=True)
    except (InvalidToken, get_user_model().DoesNotExist, ValueError):
        return None
    return user


@transaction.atomic
def rotate_refresh_token(raw_token, app_registration=None):
    payload = decode_token(raw_token, 'refresh')
    expected_registration = str(app_registration.pk) if app_registration else None
    if payload.get('app_registration') != expected_registration:
        raise InvalidToken
    token = RefreshToken.objects.select_for_update().filter(
        jti=payload['jti'],
        user_id=payload['sub'],
        revoked_at__isnull=True,
        expires_at__gt=timezone.now(),
        app_registration=app_registration,
    ).first()
    if token is None or not token.user.is_active:
        raise InvalidToken
    token.revoked_at = timezone.now()
    token.save(update_fields=['revoked_at'])
    return issue_token_pair(token.user, app_registration)


def revoke_refresh_token(raw_token):
    payload = decode_token(raw_token, 'refresh')
    RefreshToken.objects.filter(
        jti=payload['jti'],
        user_id=payload['sub'],
        revoked_at__isnull=True,
    ).update(revoked_at=timezone.now())
