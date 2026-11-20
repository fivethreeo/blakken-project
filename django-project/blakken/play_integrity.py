import base64
import hashlib
import re
import time

import google.auth
from google.auth.exceptions import DefaultCredentialsError, RefreshError, TransportError
from google.auth.transport.requests import AuthorizedSession
from requests.exceptions import RequestException


PLAY_INTEGRITY_SCOPE = 'https://www.googleapis.com/auth/playintegrity'
TOKEN_DECODE_URL = 'https://playintegrity.googleapis.com/v1/{package_name}:decodeIntegrityToken'
MAX_TOKEN_AGE_MILLISECONDS = 120_000
MAX_FUTURE_SKEW_MILLISECONDS = 30_000


def normalize_certificate_digest(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}=?', value):
        return None
    try:
        decoded = base64.b64decode(
            value + '=' * ((4 - len(value) % 4) % 4),
            altchars=b'-_',
            validate=True,
        )
    except ValueError:
        return None
    if len(decoded) != 32:
        return None
    return base64.urlsafe_b64encode(decoded).decode().rstrip('=')


class InvalidPlayIntegrity(ValueError):
    pass


class PlayIntegrityUnavailable(Exception):
    pass


def play_integrity_request_hash(challenge, body_hash, package_name, appid, menu_id):
    if len(challenge) != 32 or len(body_hash) != 32:
        raise ValueError('Play Integrity challenge and body hash must be 32 bytes.')
    request_data = (
        f'POST\n{package_name}\n{appid}\n{menu_id}\n'.encode()
        + challenge
        + body_hash
    )
    digest = hashlib.sha256(request_data).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip('=')


def decode_integrity_token(token, package_name):
    try:
        credentials, _ = google.auth.default(scopes=[PLAY_INTEGRITY_SCOPE])
    except DefaultCredentialsError as error:
        raise PlayIntegrityUnavailable('Google Play Integrity credentials are unavailable.') from error

    session = AuthorizedSession(credentials)
    try:
        response = session.post(
            TOKEN_DECODE_URL.format(package_name=package_name),
            json={'integrityToken': token},
            timeout=(5, 15),
        )
    except (DefaultCredentialsError, RefreshError, TransportError, RequestException) as error:
        raise PlayIntegrityUnavailable('Google Play Integrity verification is unavailable.') from error
    finally:
        session.close()

    if response.status_code == 400:
        raise InvalidPlayIntegrity('Google rejected the integrity token.')
    if response.status_code != 200:
        raise PlayIntegrityUnavailable('Google Play Integrity verification is unavailable.')
    try:
        payload = response.json()['tokenPayloadExternal']
    except (KeyError, TypeError, ValueError) as error:
        raise InvalidPlayIntegrity('Google returned an invalid integrity payload.') from error
    if not isinstance(payload, dict):
        raise InvalidPlayIntegrity('Google returned an invalid integrity payload.')
    return payload


def verify_integrity_payload(
    payload,
    expected_request_hash,
    package_name,
    expected_certificate_digests,
    now_milliseconds=None,
):
    if not isinstance(payload, dict):
        raise InvalidPlayIntegrity('Invalid integrity payload.')
    request_details = payload.get('requestDetails')
    app_integrity = payload.get('appIntegrity')
    device_integrity = payload.get('deviceIntegrity')
    account_details = payload.get('accountDetails')
    if not all(isinstance(value, dict) for value in (
            request_details, app_integrity, device_integrity, account_details,
    )):
        raise InvalidPlayIntegrity('Missing integrity verdicts.')

    timestamp = request_details.get('timestampMillis')
    try:
        timestamp_milliseconds = int(timestamp)
    except (TypeError, ValueError) as error:
        raise InvalidPlayIntegrity('Invalid integrity token timestamp.') from error
    if now_milliseconds is None:
        now_milliseconds = int(time.time() * 1000)
    token_age = now_milliseconds - timestamp_milliseconds
    if not -MAX_FUTURE_SKEW_MILLISECONDS <= token_age <= MAX_TOKEN_AGE_MILLISECONDS:
        raise InvalidPlayIntegrity('Stale integrity token.')

    if (
        request_details.get('requestPackageName') != package_name
        or request_details.get('requestHash') != expected_request_hash
    ):
        raise InvalidPlayIntegrity('Integrity token does not match this order.')
    if (
        app_integrity.get('appRecognitionVerdict') != 'PLAY_RECOGNIZED'
        or app_integrity.get('packageName') != package_name
    ):
        raise InvalidPlayIntegrity('App is not recognized by Google Play.')
    returned_digests = app_integrity.get('certificateSha256Digest')
    expected_digests = {
        digest
        for value in expected_certificate_digests
        if (digest := normalize_certificate_digest(value)) is not None
    }
    if (
        not isinstance(returned_digests, list)
        or not any(
            normalize_certificate_digest(digest) in expected_digests
            for digest in returned_digests
        )
    ):
        raise InvalidPlayIntegrity('App signing certificate is not recognized.')

    device_verdicts = device_integrity.get('deviceRecognitionVerdict')
    if (
        not isinstance(device_verdicts, list)
        or 'MEETS_DEVICE_INTEGRITY' not in device_verdicts
    ):
        raise InvalidPlayIntegrity('Device integrity requirements were not met.')
    if account_details.get('appLicensingVerdict') != 'LICENSED':
        raise InvalidPlayIntegrity('The app is not licensed through Google Play.')
