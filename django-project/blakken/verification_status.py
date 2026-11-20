import re

import google.auth
from cryptography import x509
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from requests import Session
from requests.exceptions import RequestException

from .app_attest import ROOT_CERTIFICATE
from .models import NativeAppRegistration, Restaurant
from .play_integrity import PLAY_INTEGRITY_SCOPE, normalize_certificate_digest


def check_google_credentials():
    with Session() as session:
        transport = Request(session=session)

        def bounded_request(*args, **kwargs):
            kwargs['timeout'] = 5
            return transport(*args, **kwargs)

        try:
            credentials, _project = google.auth.default(
                scopes=[PLAY_INTEGRITY_SCOPE], request=bounded_request,
            )
            credentials.refresh(bounded_request)
            if not credentials.valid:
                raise ValueError('No valid access token.')
        except (GoogleAuthError, RequestException, OSError, ValueError):
            return {
                'checked': True,
                'ok': False,
                'message': _(
                    'Could not obtain a Google OAuth access token. Configure Application Default '
                    'Credentials for the Django process, and check credential validity and connectivity.'
                ),
            }
    return {
        'checked': True,
        'ok': True,
        'message': _(
            'Google OAuth access token obtained. This does not confirm Play Integrity API enablement, '
            'Play Console linking, app permissions, or a valid device verdict.'
        ),
    }


def _apple_root_available():
    try:
        certificate = x509.load_pem_x509_certificate(ROOT_CERTIFICATE.read_bytes())
        now = timezone.now()
        return certificate.not_valid_before_utc <= now <= certificate.not_valid_after_utc
    except (OSError, ValueError):
        return False


def _app_status(app, apple_root_available):
    try:
        app.full_clean(exclude={'restaurant'}, validate_unique=False, validate_constraints=False)
        valid_fields = True
    except ValidationError:
        valid_fields = False
    checks = [
        {'label': _('App configuration enabled'), 'ok': app.enabled},
        {'label': _('App fields and restaurant binding valid'), 'ok': valid_fields},
    ]
    if app.platform == NativeAppRegistration.Platform.ANDROID:
        checks.extend([
            {'label': _('Play Integrity provider enabled'), 'ok': settings.PLAY_INTEGRITY_ENABLED},
            {
                'label': _('Android package name valid'),
                'ok': bool(re.fullmatch(r'[A-Za-z]\w*(?:\.[A-Za-z]\w*)+', app.app_id, flags=re.ASCII)),
            },
            {
                'label': _('Play App Signing certificate digests configured'),
                'ok': (
                    isinstance(app.certificate_digests, list)
                    and bool(app.certificate_digests)
                    and all(normalize_certificate_digest(value) for value in app.certificate_digests)
                ),
            },
        ])
    else:
        checks.extend([
            {'label': _('App Attest provider enabled'), 'ok': settings.APP_ATTEST_ENABLED},
            {
                'label': _('Apple App ID prefix and bundle ID configured'),
                'ok': bool(re.fullmatch(r'[A-Za-z0-9]+\.[A-Za-z0-9.-]+', app.app_id)),
            },
            {'label': _('Bundled Apple trust root valid'), 'ok': apple_root_available},
        ])
    if app.role == NativeAppRegistration.Role.CUSTOMER:
        checks.append({
            'label': _('Restaurant active'),
            'ok': app.restaurant_id is not None and app.restaurant.active,
        })
    return {'app': app, 'checks': checks, 'local_ok': all(check['ok'] for check in checks)}


def verification_status_context():
    apple_root_available = _apple_root_available()
    apps = [
        _app_status(app, apple_root_available)
        for app in NativeAppRegistration.objects.select_related('restaurant').order_by('name', 'pk')
    ]
    tenants = []
    for restaurant in Restaurant.objects.order_by('name', 'pk'):
        configurations = [row for row in apps if row['app'].restaurant_id == restaurant.pk]
        tenants.append({
            'restaurant': restaurant,
            'configured_apps': len(configurations),
            'local_app_available': any(row['local_ok'] for row in configurations),
        })
    return {
        'apps': apps,
        'tenants': tenants,
        'app_attest_enabled': settings.APP_ATTEST_ENABLED,
        'play_integrity_enabled': settings.PLAY_INTEGRITY_ENABLED,
        'apple_root_available': apple_root_available,
        'management_verification_required': settings.MANAGEMENT_REQUIRE_APP_VERIFICATION,
        'management_local_app_available': any(
            row['local_ok'] and row['app'].role == NativeAppRegistration.Role.MANAGEMENT
            for row in apps
        ),
        'google_credentials': {
            'checked': False,
            'ok': False,
            'message': _('Not checked. Credential discovery and network access run only when requested.'),
        },
    }
