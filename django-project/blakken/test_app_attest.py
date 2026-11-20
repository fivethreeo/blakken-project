import base64
import hashlib
import json
from datetime import timedelta
from uuid import UUID, uuid4

import cbor2
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from .app_attest import (
    AttestationResult, InvalidAppAttest, _der_octet_string, assertion_client_data_hash,
    verify_assertion, verify_attestation,
)
from .models import (
    AppAttestChallenge, AppAttestKey, Dish, Menu, MenuPage, NativeAppRegistration, Order, Restaurant,
)


class AppAttestVerifierTests(TestCase):
    def setUp(self):
        self.app_id = 'TEAMID.no.blakken.restaurants.maharaja'
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.public_key = self.private_key.public_key()
        self.public_key_pem = self.public_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        self.client_data_hash = hashlib.sha256(b'bound request').digest()

    def assertion(self, counter=1, category=4, client_data_hash=None):
        auth_data = (
            hashlib.sha256(self.app_id.encode()).digest()
            + b'\x80'
            + counter.to_bytes(4, 'big')
            + cbor2.dumps({
                'apple_validation_category_01': category.to_bytes(4, 'little'),
                'apple_bundle_version_01': '1',
            })
        )
        signature = self.private_key.sign(
            auth_data + (client_data_hash or self.client_data_hash),
            ec.ECDSA(hashes.SHA256()),
        )
        return cbor2.dumps({'authenticatorData': auth_data, 'signature': signature})

    def test_assertion_verifies_signature_claims_and_advances_counter(self):
        counter, category, version = verify_assertion(
            self.assertion(), self.public_key_pem, self.app_id,
            self.client_data_hash, 0,
        )
        self.assertEqual((counter, category, version), (1, 4, '1'))

    def test_assertion_rejects_replayed_counter_and_wrong_request_hash(self):
        with self.assertRaises(InvalidAppAttest):
            verify_assertion(
                self.assertion(), self.public_key_pem, self.app_id,
                self.client_data_hash, 1,
            )
        with self.assertRaises(InvalidAppAttest):
            verify_assertion(
                self.assertion(), self.public_key_pem, self.app_id,
                hashlib.sha256(b'other request').digest(), 0,
            )

    def test_attestation_rejects_invalid_cbor(self):
        with self.assertRaises(InvalidAppAttest):
            verify_attestation(b'not-cbor', base64.b64encode(b'k' * 32).decode(),
                               self.client_data_hash, self.app_id)

    def test_nonce_extension_decodes_apple_der_wrapper(self):
        nonce = b'n' * 32
        extension = b'\x30\x24\xa1\x22\x04\x20' + nonce
        self.assertEqual(_der_octet_string(extension), nonce)

    def test_assertion_client_data_hash_binds_restaurant_and_menu(self):
        challenge = b'c' * 32
        request_hash = hashlib.sha256(b'order').hexdigest()
        original = assertion_client_data_hash(
            challenge, request_hash, 'ca7a0000-0000-4000-8000-000000000001', 42,
        )
        self.assertNotEqual(
            original,
            assertion_client_data_hash(
                challenge, request_hash, 'ca7a0000-0000-4000-8000-000000000002', 42,
            ),
        )
        self.assertNotEqual(
            original,
            assertion_client_data_hash(
                challenge, request_hash, 'ca7a0000-0000-4000-8000-000000000001', 43,
            ),
        )


@override_settings(
    APP_ATTEST_ENABLED=True,
    PLAY_INTEGRITY_ENABLED=True,
)
class AppAttestEndpointTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(
            name='Attested Restaurant',
            appid=UUID('ca7a0000-0000-4000-8000-000000000001'),
            active=True,
        )
        self.registration = NativeAppRegistration.objects.create(
            name='Maharaja iOS', platform='ios', role='customer', restaurant=self.restaurant,
            app_id='TEAMID.no.blakken.restaurants.maharaja', enabled=True,
        )
        NativeAppRegistration.objects.create(
            name='Maharaja Android', platform='android', role='customer', restaurant=self.restaurant,
            app_id='no.blakken.restaurants.maharaja', enabled=True,
            certificate_digests=[base64.urlsafe_b64encode(b'g' * 32).decode()],
        )
        self.client.defaults['HTTP_X_APP_REGISTRATION_ID'] = str(self.registration.pk)
        self.menu = Menu.objects.create(pk=42, restaurant=self.restaurant, name='Attested Dinner')
        self.page = MenuPage.objects.create(
            menu=self.menu, name='Mains', heading='Mains', decorative_title='Dinner',
        )
        self.dish = Dish.objects.create(menu_page=self.page, name='Curry', price='125.50')
        self.client.get(reverse('customer-session'))
        self.channel = self.client.session['order_channel']

    def test_challenges_are_one_time_session_bound_and_return_random_nonce(self):
        response = self.client.post(
            reverse('app-attest-challenge'),
            {'purpose': 'attestation'},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        challenge = AppAttestChallenge.objects.get(pk=response.json()['challenge_id'])
        self.assertEqual(str(challenge.customer_channel), self.channel)
        self.assertEqual(len(bytes(challenge.challenge)), 32)
        self.assertEqual(base64.b64decode(response.json()['challenge']), bytes(challenge.challenge))
        self.assertEqual(challenge.purpose, AppAttestChallenge.Purpose.ATTESTATION)

    def test_attestation_registers_a_key_and_consumes_its_challenge_once(self):
        challenge_response = self.client.post(
            reverse('app-attest-challenge'),
            {'purpose': 'attestation'},
            content_type='application/json',
        )
        challenge_id = challenge_response.json()['challenge_id']
        key_id = base64.b64encode(b'k' * 32).decode()
        result = AttestationResult(
            public_key='test public key',
            counter=0,
            bundle_version='1',
            validation_category=4,
        )
        with patch('blakken.app_attest_views.verify_attestation', return_value=result):
            response = self.client.post(
                reverse('app-attest-key'),
                {'key_id': key_id, 'challenge_id': challenge_id,
                 'attestation_object': base64.b64encode(b'test').decode()},
                content_type='application/json',
            )
        self.assertEqual(response.status_code, 201)
        key = AppAttestKey.objects.get(key_id=key_id)
        self.assertEqual(str(key.customer_channel), self.channel)
        self.assertEqual(key.counter, 0)
        challenge = AppAttestChallenge.objects.get(pk=challenge_id)
        self.assertIsNotNone(challenge.consumed_at)

    def test_attest_endpoints_fail_closed_when_server_configuration_is_disabled(self):
        with override_settings(APP_ATTEST_ENABLED=False):
            response = self.client.post(
                reverse('app-attest-challenge'),
                {'purpose': 'attestation'},
                content_type='application/json',
            )
        self.assertEqual(response.status_code, 503)

    def test_official_order_fails_closed_without_a_valid_assertion(self):
        response = self.client.post(
            reverse('attested-create-order', args=[self.restaurant.appid, self.menu.pk]),
            {'submission_id': str(uuid4()), 'customer_name': 'Guest', 'phone': '12345678',
             'note': '', 'items': [{'dish_id': self.dish.pk, 'quantity': 1}]},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(Order.objects.count(), 0)

    def test_valid_assertion_authorizes_order_and_advances_persisted_counter(self):
        body = json.dumps({
            'submission_id': str(uuid4()),
            'customer_name': 'Guest',
            'phone': '12345678',
            'note': '',
            'items': [{'dish_id': self.dish.pk, 'quantity': 1}],
        }, separators=(',', ':')).encode()
        request_hash = hashlib.sha256(body).hexdigest()
        challenge = AppAttestChallenge.objects.create(
            customer_channel=self.channel,
            app_registration=self.registration,
            purpose=AppAttestChallenge.Purpose.ASSERTION,
            challenge=b'n' * 32,
            request_hash=request_hash,
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key = private_key.public_key()
        public_key_pem = public_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        key_id = base64.b64encode(b'k' * 32).decode()
        key = AppAttestKey.objects.create(
            key_id=key_id,
            customer_channel=self.channel,
            app_registration=self.registration,
            public_key=public_key_pem,
            app_id='TEAMID.no.blakken.restaurants.maharaja',
            bundle_version='1',
            validation_category=4,
            environment=AppAttestKey.Environment.PRODUCTION,
        )
        client_data_hash = assertion_client_data_hash(
            bytes(challenge.challenge), request_hash, self.restaurant.appid, self.menu.pk,
        )
        auth_data = (
            hashlib.sha256(key.app_id.encode()).digest()
            + b'\x80'
            + (1).to_bytes(4, 'big')
            + cbor2.dumps({
                'apple_validation_category_01': (4).to_bytes(4, 'little'),
                'apple_bundle_version_01': '1',
            })
        )
        assertion = cbor2.dumps({
            'authenticatorData': auth_data,
            'signature': private_key.sign(
                auth_data + client_data_hash,
                ec.ECDSA(hashes.SHA256()),
            ),
        })
        response = self.client.post(
            reverse('attested-create-order', args=[self.restaurant.appid, self.menu.pk]),
            body,
            content_type='application/json',
            HTTP_X_APP_ATTEST_KEY_ID=key_id,
            HTTP_X_APP_ATTEST_CHALLENGE_ID=str(challenge.pk),
            HTTP_X_APP_ATTEST_ASSERTION=base64.b64encode(assertion).decode(),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Order.objects.count(), 1)
        key.refresh_from_db()
        challenge.refresh_from_db()
        self.assertEqual(key.counter, 1)
        self.assertIsNotNone(challenge.consumed_at)

    def test_assertion_challenge_is_bound_to_exact_order_body(self):
        body = (
            b'{"submission_id":"00000000-0000-4000-8000-000000000001",'
            b'"customer_name":"Guest","phone":"12345678","note":"",'
            b'"items":[{"dish_id":1,"quantity":1}]}'
        )
        challenge = AppAttestChallenge.objects.create(
            customer_channel=self.channel,
            app_registration=self.registration,
            purpose=AppAttestChallenge.Purpose.ASSERTION,
            challenge=b'n' * 32,
            request_hash=hashlib.sha256(body + b'changed').hexdigest(),
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        key = AppAttestKey.objects.create(
            key_id='test-key-id',
            customer_channel=self.channel,
            app_registration=self.registration,
            public_key='not-used',
            app_id='TEAMID.no.blakken.restaurants.maharaja',
            bundle_version='1',
            validation_category=4,
            environment=AppAttestKey.Environment.PRODUCTION,
        )
        response = self.client.post(
            reverse('attested-create-order', args=[self.restaurant.appid, self.menu.pk]),
            body,
            content_type='application/json',
            HTTP_X_APP_ATTEST_KEY_ID=key.key_id,
            HTTP_X_APP_ATTEST_CHALLENGE_ID=str(challenge.pk),
            HTTP_X_APP_ATTEST_ASSERTION=base64.b64encode(b'not-cbor').decode(),
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(Order.objects.count(), 0)
        challenge.refresh_from_db()
        self.assertIsNone(challenge.consumed_at)
