import base64
import hashlib
import json
from unittest.mock import patch
from uuid import uuid4

import cbor2
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .app_attest import AttestationResult
from .models import (
    AppAttestKey, Dish, Menu, MenuPage, NativeAppRegistration, Order, RefreshToken,
    Restaurant, RestaurantMembership,
)
from .tokens import decode_token


@override_settings(
    APP_ATTEST_ENABLED=True, PLAY_INTEGRITY_ENABLED=True,
    MANAGEMENT_REQUIRE_APP_VERIFICATION=True,
)
class NativeAppIntegrationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='manager@example.test', email='manager@example.test', password='test-password',
        )
        self.credentials = {'email': self.user.email, 'password': 'test-password'}
        self.restaurants = []
        self.menus = []
        self.dishes = []
        self.customers = {}
        self.managers = {}
        self.digest = base64.urlsafe_b64encode(b'c' * 32).decode().rstrip('=')
        for index in range(2):
            restaurant = Restaurant.objects.create(name=f'Restaurant {index}', active=True)
            menu = Menu.objects.create(name='Dinner', restaurant=restaurant)
            page = MenuPage.objects.create(menu=menu, name='Mains')
            self.restaurants.append(restaurant)
            self.menus.append(menu)
            self.dishes.append(Dish.objects.create(menu_page=page, name='Curry', price='125.00'))
            for platform in ('ios', 'android'):
                self.customers[index, platform] = self.registration(
                    platform, f'customer{index}', restaurant,
                )
        for platform in ('ios', 'android'):
            self.managers[platform] = self.registration(platform, 'management')
        RestaurantMembership.objects.create(user=self.user, restaurant=self.restaurants[0])
        self.private_keys = {}
        self.google_payloads = {}
        self.client.get(reverse('customer-session'))
        self.decode_patch = patch(
            'blakken.play_integrity_views.decode_integrity_token',
            side_effect=lambda token, package: self.google_payloads[token],
        )
        self.decode_patch.start()
        self.addCleanup(self.decode_patch.stop)

    def registration(self, platform, name, restaurant=None):
        return NativeAppRegistration.objects.create(
            name=f'{name} {platform}', platform=platform,
            role='customer' if restaurant else 'management', restaurant=restaurant,
            app_id=f'TEAM.no.blakken.{name}' if platform == 'ios' else f'no.blakken.{name}',
            certificate_digests=[self.digest] if platform == 'android' else [],
            enabled=True,
        )

    def proof(self, registration, body, operation='token', tenant=None, client=None):
        client = client or self.client
        session = client.get(reverse('customer-session')).json()
        headers = {
            'HTTP_X_APP_REGISTRATION_ID': str(registration.pk),
            'HTTP_X_CSRFTOKEN': session['csrf_token'],
        }
        body_hash = hashlib.sha256(body).digest()
        apple = registration.platform == 'ios'
        challenge_response = client.post(
            reverse('app-attest-challenge' if apple else 'play-integrity-challenge'),
            {'purpose': 'assertion', 'request_hash': body_hash.hex()} if apple
            else {'request_hash': body_hash.hex()},
            content_type='application/json', **headers,
        )
        self.assertEqual(challenge_response.status_code, 200, challenge_response.content)
        challenge = challenge_response.json()
        nonce = base64.b64decode(challenge['challenge'])
        if tenant is None:
            scope = f'POST\nmanagement\n{registration.pk}\n{operation}\n'
        else:
            restaurant, menu = tenant
            scope = f'POST\n{restaurant.appid}\n{menu.pk}\n'
            if not apple:
                scope = f'POST\n{registration.app_id}\n{restaurant.appid}\n{menu.pk}\n'
        digest = hashlib.sha256(scope.encode() + nonce + body_hash).digest()
        if apple:
            if registration.pk not in self.private_keys:
                private_key = ec.generate_private_key(ec.SECP256R1())
                key = AppAttestKey.objects.create(
                    key_id=base64.b64encode(uuid4().bytes * 2).decode(),
                    customer_channel=client.session['order_channel'],
                    app_registration=registration, app_id=registration.app_id,
                    public_key=private_key.public_key().public_bytes(
                        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
                    ).decode(),
                    bundle_version='1', validation_category=4, environment='production',
                )
                self.private_keys[registration.pk] = (private_key, key)
            private_key, key = self.private_keys[registration.pk]
            key.refresh_from_db()
            auth_data = (
                hashlib.sha256(registration.app_id.encode()).digest() + b'\x80'
                + (key.counter + 1).to_bytes(4, 'big')
                + cbor2.dumps({
                    'apple_validation_category_01': (4).to_bytes(4, 'little'),
                    'apple_bundle_version_01': '1',
                })
            )
            assertion = cbor2.dumps({
                'authenticatorData': auth_data,
                'signature': private_key.sign(auth_data + digest, ec.ECDSA(hashes.SHA256())),
            })
            headers.update({
                'HTTP_X_APP_ATTEST_KEY_ID': key.key_id,
                'HTTP_X_APP_ATTEST_CHALLENGE_ID': challenge['challenge_id'],
                'HTTP_X_APP_ATTEST_ASSERTION': base64.b64encode(assertion).decode(),
            })
        else:
            token = str(uuid4())
            self.google_payloads[token] = {
                'requestDetails': {
                    'requestPackageName': registration.app_id,
                    'requestHash': base64.urlsafe_b64encode(digest).decode().rstrip('='),
                    'timestampMillis': str(int(timezone.now().timestamp() * 1000)),
                },
                'appIntegrity': {
                    'appRecognitionVerdict': 'PLAY_RECOGNIZED',
                    'packageName': registration.app_id,
                    'certificateSha256Digest': registration.certificate_digests,
                },
                'deviceIntegrity': {'deviceRecognitionVerdict': ['MEETS_DEVICE_INTEGRITY']},
                'accountDetails': {'appLicensingVerdict': 'LICENSED'},
            }
            headers.update({
                'HTTP_X_PLAY_INTEGRITY_TOKEN': token,
                'HTTP_X_PLAY_INTEGRITY_CHALLENGE_ID': challenge['challenge_id'],
            })
        return headers

    def management_request(self, registration, operation, data, signed_operation=None):
        body = json.dumps(data).encode()
        headers = self.proof(registration, body, signed_operation or operation)
        response = self.client.post(
            reverse('management-attested-auth', args=[registration.platform, operation]),
            body, content_type='application/json', **headers,
        )
        return response, body, headers

    def order_body(self, index):
        return json.dumps({
            'submission_id': str(uuid4()), 'customer_name': 'Guest', 'phone': '12345678',
            'note': '', 'items': [{'dish_id': self.dishes[index].pk, 'quantity': 1}],
        }).encode()

    def order_url(self, platform, index):
        return reverse(
            'attested-create-order' if platform == 'ios' else 'play-integrity-create-order',
            args=[self.restaurants[index].appid, self.menus[index].pk],
        )

    def test_multiple_restaurants_accept_only_their_registered_apps_on_both_platforms(self):
        for platform in ('ios', 'android'):
            for index in range(2):
                with self.subTest(platform=platform, restaurant=index):
                    registration = self.customers[index, platform]
                    body = self.order_body(index)
                    headers = self.proof(
                        registration, body, tenant=(self.restaurants[index], self.menus[index]),
                    )
                    wrong = self.client.post(
                        self.order_url(platform, 1 - index), body,
                        content_type='application/json', **headers,
                    )
                    self.assertEqual(wrong.status_code, 404)
                    accepted = self.client.post(
                        self.order_url(platform, index), body,
                        content_type='application/json', **headers,
                    )
                    self.assertEqual(accepted.status_code, 201, accepted.content)
        self.assertEqual(Order.objects.filter(restaurant=self.restaurants[0]).count(), 2)
        self.assertEqual(Order.objects.filter(restaurant=self.restaurants[1]).count(), 2)

    def test_either_customer_platform_blocks_regular_orders_even_if_providers_are_disabled(self):
        body = self.order_body(0)
        url = reverse('restaurant-create-order', args=[self.restaurants[0].appid, self.menus[0].pk])
        for platform in ('ios', 'android'):
            NativeAppRegistration.objects.filter(role='customer').update(enabled=False)
            NativeAppRegistration.objects.filter(pk=self.customers[0, platform].pk).update(enabled=True)
            for provider_enabled in (True, False):
                with self.subTest(platform=platform, provider_enabled=provider_enabled), override_settings(
                    APP_ATTEST_ENABLED=provider_enabled, PLAY_INTEGRITY_ENABLED=provider_enabled,
                ):
                    response = self.client.post(url, body, content_type='application/json')
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(response.json()['code'], 'app_verification_required')
        self.assertFalse(Order.objects.exists())

    def test_regular_order_opt_out_is_explicit_and_tenant_local_even_with_configured_apps(self):
        restaurant = self.restaurants[1]
        restaurant.require_verified_orders = False
        restaurant.save(update_fields=['require_verified_orders'])
        for index, expected in [(0, 403), (1, 201)]:
            response = self.client.post(
                reverse('restaurant-create-order', args=[self.restaurants[index].appid, self.menus[index].pk]),
                self.order_body(index), content_type='application/json',
            )
            self.assertEqual(response.status_code, expected)
        self.assertFalse(Order.objects.filter(restaurant=self.restaurants[0]).exists())
        self.assertEqual(Order.objects.filter(restaurant=self.restaurants[1]).count(), 1)

    def test_proof_headers_on_regular_route_do_not_bypass_verification_or_consume_proof(self):
        self.user.is_staff = True
        self.user.save(update_fields=['is_staff'])
        self.client.force_login(self.user)
        for platform in ('ios', 'android'):
            body = self.order_body(0)
            headers = self.proof(
                self.customers[0, platform], body, tenant=(self.restaurants[0], self.menus[0]),
            )
            regular_url = reverse(
                'restaurant-create-order', args=[self.restaurants[0].appid, self.menus[0].pk],
            )
            regular = self.client.post(
                regular_url, body, content_type='application/json', **headers,
            )
            self.assertEqual(regular.status_code, 403)
            strict = self.client.post(
                self.order_url(platform, 0), body, content_type='application/json', **headers,
            )
            self.assertEqual(strict.status_code, 201, strict.content)
            regular_retry = self.client.post(regular_url, body, content_type='application/json')
            self.assertEqual(regular_retry.status_code, 403)
        self.assertEqual(Order.objects.count(), 2)

    def test_enabling_verification_blocks_old_order_retries_but_verified_retries_remain_idempotent(self):
        restaurant = self.restaurants[0]
        restaurant.require_verified_orders = False
        restaurant.save(update_fields=['require_verified_orders'])
        body = self.order_body(0)
        url = reverse('restaurant-create-order', args=[self.restaurants[0].appid, self.menus[0].pk])
        saved = self.client.post(url, body, content_type='application/json')
        self.assertEqual(saved.status_code, 201)
        restaurant.require_verified_orders = True
        restaurant.save(update_fields=['require_verified_orders'])
        self.assertEqual(
            self.client.post(url, body, content_type='application/json').status_code, 403,
        )
        for platform in ('ios', 'android'):
            headers = self.proof(
                self.customers[0, platform], body, tenant=(self.restaurants[0], self.menus[0]),
            )
            retry = self.client.post(
                self.order_url(platform, 0), body, content_type='application/json', **headers,
            )
            self.assertEqual(retry.status_code, 200, retry.content)
            self.assertEqual(retry.json()['order']['id'], saved.json()['order']['id'])
        self.assertEqual(Order.objects.count(), 1)

    def test_challenges_cannot_move_between_registrations_even_in_same_session(self):
        for platform in ('ios', 'android'):
            body = self.order_body(0)
            headers = self.proof(
                self.customers[0, platform], body, tenant=(self.restaurants[0], self.menus[0]),
            )
            headers['HTTP_X_APP_REGISTRATION_ID'] = str(self.customers[1, platform].pk)
            response = self.client.post(
                self.order_url(platform, 1), body, content_type='application/json', **headers,
            )
            self.assertEqual(response.status_code, 401)
        self.assertFalse(Order.objects.exists())

    def test_disabling_one_registration_does_not_disable_another_tenant_or_platform(self):
        disabled = self.customers[0, 'ios']
        disabled.enabled = False
        disabled.save()
        for registration, expected in [
            (disabled, 503), (self.customers[1, 'ios'], 200),
            (self.customers[0, 'android'], 200), (self.managers['ios'], 200),
        ]:
            apple = registration.platform == 'ios'
            response = self.client.post(
                reverse('app-attest-challenge' if apple else 'play-integrity-challenge'),
                {'purpose': 'attestation'} if apple else {'request_hash': 'a' * 64},
                content_type='application/json',
                HTTP_X_APP_REGISTRATION_ID=str(registration.pk),
            )
            self.assertEqual(response.status_code, expected)

    def test_management_login_and_refresh_require_matching_app_and_cannot_use_legacy_refresh(self):
        for platform in ('ios', 'android'):
            with self.subTest(platform=platform):
                registration = self.managers[platform]
                login, body, headers = self.management_request(registration, 'token', self.credentials)
                self.assertEqual(login.status_code, 200, login.content)
                tokens = login.json()
                claims = decode_token(tokens['refresh'], 'refresh')
                self.assertEqual(claims['app_registration'], str(registration.pk))
                stored = RefreshToken.objects.get(jti=claims['jti'])
                self.assertEqual(stored.app_registration, registration)
                replay = self.client.post(
                    reverse('management-attested-auth', args=[platform, 'token']),
                    body, content_type='application/json', **headers,
                )
                self.assertEqual(replay.status_code, 401)
                legacy = self.client.post(
                    reverse('api-refresh'), {'refresh': tokens['refresh']},
                    content_type='application/json',
                )
                self.assertEqual(legacy.status_code, 403)
                with override_settings(MANAGEMENT_REQUIRE_APP_VERIFICATION=False):
                    legacy_opt_out = self.client.post(
                        reverse('api-refresh'), {'refresh': tokens['refresh']},
                        content_type='application/json',
                    )
                self.assertEqual(legacy_opt_out.status_code, 401)
                other = self.registration(platform, f'othermanager{platform}')
                wrong, _, _ = self.management_request(other, 'refresh', {'refresh': tokens['refresh']})
                self.assertEqual(wrong.status_code, 401)
                refreshed, _, _ = self.management_request(
                    registration, 'refresh', {'refresh': tokens['refresh']},
                )
                self.assertEqual(refreshed.status_code, 200, refreshed.content)
                stored.refresh_from_db()
                self.assertIsNotNone(stored.revoked_at)
                self.assertEqual(
                    decode_token(refreshed.json()['refresh'], 'refresh')['app_registration'],
                    str(registration.pk),
                )

    def test_management_proof_is_bound_to_login_or_refresh_operation_and_exact_body(self):
        for platform in ('ios', 'android'):
            registration = self.managers[platform]
            response, _, _ = self.management_request(
                registration, 'token', self.credentials, signed_operation='refresh',
            )
            self.assertEqual(response.status_code, 401)
            body = json.dumps(self.credentials).encode()
            headers = self.proof(registration, body)
            response = self.client.post(
                reverse('management-attested-auth', args=[platform, 'token']),
                body + b' ', content_type='application/json', **headers,
            )
            self.assertEqual(response.status_code, 401)
        self.assertFalse(RefreshToken.objects.exists())

    def test_management_attestation_does_not_grant_restaurant_membership(self):
        for platform in ('ios', 'android'):
            response, _, _ = self.management_request(self.managers[platform], 'token', self.credentials)
            token = response.json()['access']
            headers = {'HTTP_AUTHORIZATION': f'Bearer {token}'}
            restaurants = self.client.get(reverse('management-restaurants'), **headers)
            self.assertEqual(
                [item['appid'] for item in restaurants.json()['results']],
                [str(self.restaurants[0].appid)],
            )
            forbidden = self.client.get(
                reverse('management-menus', args=[self.restaurants[1].appid]), **headers,
            )
            self.assertEqual(forbidden.status_code, 403)

    def test_customer_and_management_registrations_cannot_authorize_each_others_routes(self):
        for platform in ('ios', 'android'):
            login, _, _ = self.management_request(self.customers[0, platform], 'token', self.credentials)
            self.assertEqual(login.status_code, 401)
            body = self.order_body(0)
            headers = self.proof(self.managers[platform], body)
            order = self.client.post(
                self.order_url(platform, 0), body, content_type='application/json', **headers,
            )
            self.assertEqual(order.status_code, 401)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(RefreshToken.objects.exists())

    def test_strict_login_still_requires_credentials_and_missing_proof_cannot_issue_tokens(self):
        for platform in ('ios', 'android'):
            registration = self.managers[platform]
            missing = self.client.post(
                reverse('management-attested-auth', args=[platform, 'token']),
                self.credentials, content_type='application/json',
                HTTP_X_APP_REGISTRATION_ID=str(registration.pk),
            )
            self.assertEqual(missing.status_code, 401)
            invalid, _, _ = self.management_request(
                registration, 'token', {**self.credentials, 'password': 'wrong-password'},
            )
            self.assertEqual(invalid.status_code, 401)
        self.assertFalse(RefreshToken.objects.exists())

    def test_apple_key_registration_uses_selected_app_identity(self):
        for registration in [self.customers[0, 'ios'], self.customers[1, 'ios'], self.managers['ios']]:
            headers = {'HTTP_X_APP_REGISTRATION_ID': str(registration.pk)}
            challenge = self.client.post(
                reverse('app-attest-challenge'), {'purpose': 'attestation'},
                content_type='application/json', **headers,
            ).json()
            key_id = base64.b64encode(uuid4().bytes * 2).decode()
            with patch(
                'blakken.app_attest_views.verify_attestation',
                return_value=AttestationResult('public-key', 0, '1', 4),
            ) as verify:
                response = self.client.post(
                    reverse('app-attest-key'),
                    {'key_id': key_id, 'challenge_id': challenge['challenge_id'],
                     'attestation_object': base64.b64encode(b'attestation').decode()},
                    content_type='application/json', **headers,
                )
            self.assertEqual(response.status_code, 201)
            self.assertEqual(verify.call_args.args[-1], registration.app_id)
            self.assertEqual(AppAttestKey.objects.get(key_id=key_id).app_registration, registration)

    def test_strict_management_auth_preserves_csrf_protection(self):
        client = Client(enforce_csrf_checks=True)
        registration = self.managers['android']
        body = json.dumps(self.credentials).encode()
        headers = self.proof(registration, body, client=client)
        csrf = headers.pop('HTTP_X_CSRFTOKEN')
        url = reverse('management-attested-auth', args=['android', 'token'])
        self.assertEqual(client.post(url, body, content_type='application/json', **headers).status_code, 403)
        headers['HTTP_X_CSRFTOKEN'] = csrf
        self.assertEqual(client.post(url, body, content_type='application/json', **headers).status_code, 200)

    def test_https_native_requests_supply_origin_as_well_as_csrf_and_session(self):
        for platform in ('ios', 'android'):
            client = Client(enforce_csrf_checks=True)
            body = self.order_body(0)
            headers = self.proof(
                self.customers[0, platform], body, client=client,
                tenant=(self.restaurants[0], self.menus[0]),
            )
            url = self.order_url(platform, 0)
            missing_origin = client.post(
                url, body, content_type='application/json', secure=True, **headers,
            )
            self.assertEqual(missing_origin.status_code, 403)
            response = client.post(
                url, body, content_type='application/json', secure=True,
                HTTP_ORIGIN='https://testserver', **headers,
            )
            self.assertEqual(response.status_code, 201, response.content)

    def test_legacy_refresh_cannot_upgrade_to_verified_and_registration_disable_blocks_refresh(self):
        with override_settings(MANAGEMENT_REQUIRE_APP_VERIFICATION=False):
            legacy = self.client.post(
                reverse('api-token'), self.credentials, content_type='application/json',
            ).json()['refresh']
        for platform in ('ios', 'android'):
            registration = self.managers[platform]
            upgrade, _, _ = self.management_request(registration, 'refresh', {'refresh': legacy})
            self.assertEqual(upgrade.status_code, 401)
            login, _, _ = self.management_request(registration, 'token', self.credentials)
            body = json.dumps({'refresh': login.json()['refresh']}).encode()
            headers = self.proof(registration, body, 'refresh')
            registration.enabled = False
            registration.save()
            disabled = self.client.post(
                reverse('management-attested-auth', args=[platform, 'refresh']),
                body, content_type='application/json', **headers,
            )
            self.assertEqual(disabled.status_code, 503)
        with override_settings(MANAGEMENT_REQUIRE_APP_VERIFICATION=False):
            still_legacy = self.client.post(
                reverse('api-refresh'), {'refresh': legacy}, content_type='application/json',
            )
        self.assertEqual(still_legacy.status_code, 200)

    def test_missing_or_disabled_app_configuration_cannot_unlock_regular_orders(self):
        url = reverse('restaurant-create-order', args=[self.restaurants[0].appid, self.menus[0].pk])
        body = self.order_body(0)
        configurations = NativeAppRegistration.objects.filter(restaurant=self.restaurants[0])
        configurations.update(enabled=False)
        for remove_configurations in (False, True):
            if remove_configurations:
                configurations.delete()
            with override_settings(APP_ATTEST_ENABLED=False, PLAY_INTEGRITY_ENABLED=False):
                response = self.client.post(url, body, content_type='application/json')
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()['code'], 'app_verification_required')
        self.assertFalse(Order.objects.exists())

    def test_missing_management_configuration_requires_explicit_opt_out_for_login_and_refresh(self):
        NativeAppRegistration.objects.filter(role='management').delete()
        with override_settings(APP_ATTEST_ENABLED=False, PLAY_INTEGRITY_ENABLED=False):
            blocked = self.client.post(
                reverse('api-token'), self.credentials, content_type='application/json',
            )
            self.assertEqual(blocked.status_code, 403)
            self.assertFalse(RefreshToken.objects.exists())
            with override_settings(MANAGEMENT_REQUIRE_APP_VERIFICATION=False):
                allowed = self.client.post(
                    reverse('api-token'), self.credentials, content_type='application/json',
                )
            self.assertEqual(allowed.status_code, 200)
            refresh = allowed.json()['refresh']
            denied_refresh = self.client.post(
                reverse('api-refresh'), {'refresh': refresh}, content_type='application/json',
            )
            self.assertEqual(denied_refresh.status_code, 403)
            self.assertIsNone(RefreshToken.objects.get(
                jti=decode_token(refresh, 'refresh')['jti'],
            ).revoked_at)
            with override_settings(MANAGEMENT_REQUIRE_APP_VERIFICATION=False):
                allowed_refresh = self.client.post(
                    reverse('api-refresh'), {'refresh': refresh}, content_type='application/json',
                )
            self.assertEqual(allowed_refresh.status_code, 200)

    def test_management_proof_headers_cannot_authorize_legacy_login(self):
        for platform in ('ios', 'android'):
            body = json.dumps(self.credentials).encode()
            headers = self.proof(self.managers[platform], body)
            regular = self.client.post(
                reverse('api-token'), body, content_type='application/json', **headers,
            )
            self.assertEqual(regular.status_code, 403)
            strict = self.client.post(
                reverse('management-attested-auth', args=[platform, 'token']),
                body, content_type='application/json', **headers,
            )
            self.assertEqual(strict.status_code, 200, strict.content)

    def test_registration_validation_rejects_wrong_role_binding_and_bad_certificates(self):
        registration = self.managers['android']
        registration.restaurant = self.restaurants[0]
        with self.assertRaises(ValidationError):
            registration.full_clean()
        registration.restaurant = None
        registration.certificate_digests = ['not-a-sha256-digest']
        with self.assertRaises(ValidationError):
            registration.full_clean()
