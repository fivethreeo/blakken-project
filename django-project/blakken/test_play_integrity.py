import base64
import hashlib
import json
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    AppAttestChallenge, Dish, Menu, MenuPage, NativeAppRegistration, Order,
    PlayIntegrityChallenge, Restaurant,
)
from .play_integrity import (
    InvalidPlayIntegrity,
    PlayIntegrityUnavailable,
    normalize_certificate_digest,
    play_integrity_request_hash,
    verify_integrity_payload,
)


PACKAGE_NAME = 'no.blakken.restaurants.maharaja'
RESTAURANT_APP_ID = UUID('ca7a0000-0000-4000-8000-000000000001')
CERTIFICATE_DIGEST = base64.urlsafe_b64encode(hashlib.sha256(b'play-signing-cert').digest()).decode().rstrip('=')


class PlayIntegrityVerifierTests(TestCase):
    def setUp(self):
        self.request_hash = 'b' * 43
        self.now_milliseconds = 1_800_000_000_000
        self.payload = {
            'requestDetails': {
                'requestPackageName': PACKAGE_NAME,
                'requestHash': self.request_hash,
                'timestampMillis': str(self.now_milliseconds),
            },
            'appIntegrity': {
                'appRecognitionVerdict': 'PLAY_RECOGNIZED',
                'packageName': PACKAGE_NAME,
                'certificateSha256Digest': [CERTIFICATE_DIGEST],
            },
            'deviceIntegrity': {
                'deviceRecognitionVerdict': ['MEETS_DEVICE_INTEGRITY'],
            },
            'accountDetails': {'appLicensingVerdict': 'LICENSED'},
        }

    def test_accepts_matching_fresh_play_recognized_order(self):
        verify_integrity_payload(
            self.payload,
            self.request_hash,
            PACKAGE_NAME,
            [CERTIFICATE_DIGEST],
            self.now_milliseconds,
        )

    def test_rejects_mismatched_hash_stale_token_and_untrusted_verdicts(self):
        invalid_cases = [
            ({'requestDetails': {'requestHash': 'other'}},),
            ({'appIntegrity': {'appRecognitionVerdict': 'UNRECOGNIZED_VERSION'}},),
            ({'deviceIntegrity': {'deviceRecognitionVerdict': []}},),
            ({'accountDetails': {'appLicensingVerdict': 'UNLICENSED'}},),
        ]
        for (changes,) in invalid_cases:
            with self.subTest(changes=changes):
                payload = json.loads(json.dumps(self.payload))
                for section, values in changes.items():
                    payload[section].update(values)
                with self.assertRaises(InvalidPlayIntegrity):
                    verify_integrity_payload(
                        payload,
                        self.request_hash,
                        PACKAGE_NAME,
                        [CERTIFICATE_DIGEST],
                        self.now_milliseconds,
                    )

        payload = json.loads(json.dumps(self.payload))
        payload['requestDetails']['timestampMillis'] = str(self.now_milliseconds - 121_000)
        with self.assertRaises(InvalidPlayIntegrity):
            verify_integrity_payload(
                payload,
                self.request_hash,
                PACKAGE_NAME,
                [CERTIFICATE_DIGEST],
                self.now_milliseconds,
            )

    def test_certificate_digest_normalizes_padding_and_rejects_invalid_values(self):
        self.assertEqual(normalize_certificate_digest(CERTIFICATE_DIGEST), CERTIFICATE_DIGEST)
        self.assertEqual(
            normalize_certificate_digest(CERTIFICATE_DIGEST + '='),
            CERTIFICATE_DIGEST,
        )
        self.assertIsNone(normalize_certificate_digest('not-a-certificate-digest'))

    def test_request_hash_binds_challenge_body_restaurant_and_menu(self):
        challenge = b'c' * 32
        body_hash = hashlib.sha256(b'order').digest()
        original = play_integrity_request_hash(
            challenge, body_hash, PACKAGE_NAME, str(RESTAURANT_APP_ID), 42,
        )
        self.assertNotEqual(
            original,
            play_integrity_request_hash(
                challenge, body_hash, PACKAGE_NAME, str(RESTAURANT_APP_ID), 43,
            ),
        )
        self.assertNotEqual(
            original,
            play_integrity_request_hash(
                b'd' * 32, body_hash, PACKAGE_NAME, str(RESTAURANT_APP_ID), 42,
            ),
        )


@override_settings(
    PLAY_INTEGRITY_ENABLED=True,
    APP_ATTEST_ENABLED=True,
)
class PlayIntegrityEndpointTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(
            name='Play Integrity Restaurant',
            appid=RESTAURANT_APP_ID,
            active=True,
        )
        self.registration = NativeAppRegistration.objects.create(
            name='Maharaja Android', platform='android', role='customer', restaurant=self.restaurant,
            app_id=PACKAGE_NAME, certificate_digests=[CERTIFICATE_DIGEST], enabled=True,
        )
        self.apple_registration = NativeAppRegistration.objects.create(
            name='Maharaja iOS', platform='ios', role='customer', restaurant=self.restaurant,
            app_id='TEAMID.no.blakken.restaurants.maharaja', enabled=True,
        )
        self.client.defaults['HTTP_X_APP_REGISTRATION_ID'] = str(self.registration.pk)
        self.menu = Menu.objects.create(pk=52, restaurant=self.restaurant, name='Dinner')
        self.page = MenuPage.objects.create(
            menu=self.menu, name='Mains', heading='Mains', decorative_title='Dinner',
        )
        self.dish = Dish.objects.create(menu_page=self.page, name='Curry', price='125.50')
        self.client.get(reverse('customer-session'))
        self.channel = self.client.session['order_channel']

    def test_challenge_is_random_and_bound_to_existing_customer_session(self):
        response = self.client.post(
            reverse('play-integrity-challenge'),
            {'request_hash': 'a' * 64},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        challenge = PlayIntegrityChallenge.objects.get(pk=response.json()['challenge_id'])
        self.assertEqual(str(challenge.customer_channel), self.channel)
        self.assertEqual(len(bytes(challenge.challenge)), 32)
        self.assertEqual(
            base64.b64decode(response.json()['challenge']),
            bytes(challenge.challenge),
        )

    def test_valid_google_verdict_creates_order_and_consumes_challenge(self):
        body = json.dumps({
            'submission_id': str(uuid4()),
            'customer_name': 'Guest',
            'phone': '12345678',
            'note': '',
            'items': [{'dish_id': self.dish.pk, 'quantity': 1}],
        }, separators=(',', ':')).encode()
        body_digest = hashlib.sha256(body).digest()
        challenge = PlayIntegrityChallenge.objects.create(
            customer_channel=self.channel,
            app_registration=self.registration,
            challenge=b'c' * 32,
            request_hash=body_digest.hex(),
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        expected_hash = play_integrity_request_hash(
            bytes(challenge.challenge),
            body_digest,
            PACKAGE_NAME,
            str(self.restaurant.appid),
            self.menu.pk,
        )
        payload = {
            'requestDetails': {
                'requestPackageName': PACKAGE_NAME,
                'requestHash': expected_hash,
                'timestampMillis': str(int(timezone.now().timestamp() * 1000)),
            },
            'appIntegrity': {
                'appRecognitionVerdict': 'PLAY_RECOGNIZED',
                'packageName': PACKAGE_NAME,
                'certificateSha256Digest': [CERTIFICATE_DIGEST],
            },
            'deviceIntegrity': {
                'deviceRecognitionVerdict': ['MEETS_DEVICE_INTEGRITY'],
            },
            'accountDetails': {'appLicensingVerdict': 'LICENSED'},
        }
        with patch(
                'blakken.play_integrity_views.decode_integrity_token',
                return_value=payload,
        ) as decode:
            response = self.client.post(
                reverse('play-integrity-create-order', args=[self.restaurant.appid, self.menu.pk]),
                body,
                content_type='application/json',
                HTTP_X_PLAY_INTEGRITY_CHALLENGE_ID=str(challenge.pk),
                HTTP_X_PLAY_INTEGRITY_TOKEN='encrypted-google-token',
            )
            replay = self.client.post(
                reverse('play-integrity-create-order', args=[self.restaurant.appid, self.menu.pk]),
                body,
                content_type='application/json',
                HTTP_X_PLAY_INTEGRITY_CHALLENGE_ID=str(challenge.pk),
                HTTP_X_PLAY_INTEGRITY_TOKEN='encrypted-google-token',
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(replay.status_code, 401)
        decode.assert_called_once_with('encrypted-google-token', PACKAGE_NAME)
        self.assertEqual(Order.objects.count(), 1)
        challenge.refresh_from_db()
        self.assertIsNotNone(challenge.consumed_at)

    def test_play_integrity_is_independently_configurable_and_wrong_restaurant_is_rejected(self):
        with override_settings(PLAY_INTEGRITY_ENABLED=False):
            disabled = self.client.post(
                reverse('play-integrity-challenge'),
                {'request_hash': 'a' * 64},
                content_type='application/json',
            )
        self.assertEqual(disabled.status_code, 503)
        self.assertEqual(
            self.client.post(
                reverse('play-integrity-create-order', args=[uuid4(), self.menu.pk]),
                b'{}',
                content_type='application/json',
            ).status_code,
            404,
        )

    def test_each_provider_can_be_disabled_without_disabling_the_other(self):
        for apple_enabled, google_enabled in [(True, True), (False, True), (True, False)]:
            with self.subTest(apple=apple_enabled, google=google_enabled), override_settings(
                APP_ATTEST_ENABLED=apple_enabled,
                PLAY_INTEGRITY_ENABLED=google_enabled,
            ):
                apple = self.client.post(
                    reverse('app-attest-challenge'),
                    {'purpose': 'assertion', 'request_hash': 'a' * 64},
                    content_type='application/json',
                    HTTP_X_APP_REGISTRATION_ID=str(self.apple_registration.pk),
                )
                google = self.client.post(
                    reverse('play-integrity-challenge'),
                    {'request_hash': 'a' * 64},
                    content_type='application/json',
                )
                self.assertEqual(apple.status_code, 200 if apple_enabled else 503)
                self.assertEqual(google.status_code, 200 if google_enabled else 503)
                for route, enabled in [
                    ('attested-create-order', apple_enabled),
                    ('play-integrity-create-order', google_enabled),
                ]:
                    order = self.client.post(
                        reverse(route, args=[self.restaurant.appid, self.menu.pk]),
                        {},
                        content_type='application/json',
                        HTTP_X_APP_REGISTRATION_ID=str(
                            self.apple_registration.pk if route == 'attested-create-order'
                            else self.registration.pk
                        ),
                    )
                    self.assertEqual(order.status_code, 401 if enabled else 503)
        self.assertEqual(Order.objects.count(), 0)

    def test_challenges_cannot_cross_providers_or_customer_sessions(self):
        body = b'{}'
        body_hash = hashlib.sha256(body).hexdigest()
        apple = self.client.post(
            reverse('app-attest-challenge'),
            {'purpose': 'assertion', 'request_hash': body_hash},
            content_type='application/json',
            HTTP_X_APP_REGISTRATION_ID=str(self.apple_registration.pk),
        ).json()['challenge_id']
        google = self.client.post(
            reverse('play-integrity-challenge'),
            {'request_hash': body_hash},
            content_type='application/json',
        ).json()['challenge_id']
        other_client = Client()
        other_client.get(reverse('customer-session'))
        with patch('blakken.play_integrity_views.decode_integrity_token') as decode, patch(
            'blakken.app_attest_views.verify_assertion',
        ) as verify_apple:
            for client, provider, challenge_id in [
                (self.client, 'apple', google),
                (self.client, 'google', apple),
                (other_client, 'apple', apple),
                (other_client, 'google', google),
            ]:
                with self.subTest(provider=provider, challenge=challenge_id):
                    route, headers = (
                        ('attested-create-order', {
                            'HTTP_X_APP_ATTEST_CHALLENGE_ID': challenge_id,
                            'HTTP_X_APP_ATTEST_KEY_ID': 'test-key',
                            'HTTP_X_APP_ATTEST_ASSERTION': base64.b64encode(b'proof').decode(),
                        }) if provider == 'apple' else
                        ('play-integrity-create-order', {
                            'HTTP_X_PLAY_INTEGRITY_CHALLENGE_ID': challenge_id,
                            'HTTP_X_PLAY_INTEGRITY_TOKEN': 'test-token',
                        })
                    )
                    response = client.post(
                        reverse(route, args=[self.restaurant.appid, self.menu.pk]),
                        body,
                        content_type='application/json',
                        HTTP_X_APP_REGISTRATION_ID=str(
                            self.apple_registration.pk if provider == 'apple'
                            else self.registration.pk
                        ),
                        **headers,
                    )
                    self.assertEqual(response.status_code, 401)
            decode.assert_not_called()
            verify_apple.assert_not_called()
        self.assertEqual(Order.objects.count(), 0)
        self.assertIsNone(AppAttestChallenge.objects.get(pk=apple).consumed_at)
        self.assertIsNone(PlayIntegrityChallenge.objects.get(pk=google).consumed_at)

    def test_google_outage_does_not_consume_challenge_or_fall_back_to_legacy(self):
        body = b'{}'
        challenge = self.client.post(
            reverse('play-integrity-challenge'),
            {'request_hash': hashlib.sha256(body).hexdigest()},
            content_type='application/json',
        ).json()['challenge_id']
        with patch(
            'blakken.play_integrity_views.decode_integrity_token',
            side_effect=PlayIntegrityUnavailable,
        ):
            response = self.client.post(
                reverse('play-integrity-create-order', args=[self.restaurant.appid, self.menu.pk]),
                body,
                content_type='application/json',
                HTTP_X_PLAY_INTEGRITY_CHALLENGE_ID=challenge,
                HTTP_X_PLAY_INTEGRITY_TOKEN='test-token',
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(Order.objects.count(), 0)
        self.assertIsNone(PlayIntegrityChallenge.objects.get(pk=challenge).consumed_at)
        self.assertEqual(self.client.post(
            reverse('app-attest-challenge'),
            {'purpose': 'attestation'},
            content_type='application/json',
            HTTP_X_APP_REGISTRATION_ID=str(self.apple_registration.pk),
        ).status_code, 200)

    def test_legacy_orders_are_rejected_when_customer_verification_is_enabled(self):
        response = self.client.post(
            reverse('restaurant-create-order', args=[self.restaurant.appid, self.menu.pk]),
            {'submission_id': str(uuid4()), 'customer_name': 'Guest', 'phone': '12345678',
             'note': '', 'items': [{'dish_id': self.dish.pk, 'quantity': 1}]},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'app_verification_required')
        self.assertEqual(Order.objects.count(), 0)
