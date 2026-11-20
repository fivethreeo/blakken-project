import base64
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from google.auth.exceptions import DefaultCredentialsError, RefreshError

from .models import NativeAppRegistration, Restaurant
from .play_integrity import PLAY_INTEGRITY_SCOPE


@override_settings(
    APP_ATTEST_ENABLED=True, PLAY_INTEGRITY_ENABLED=True,
    MANAGEMENT_REQUIRE_APP_VERIFICATION=True,
)
class VerificationStatusTests(TestCase):
    def setUp(self):
        self.operator = get_user_model().objects.create_superuser(
            username='operator', email='operator@example.test', password='test-password',
        )
        self.url = reverse('admin:blakken_nativeappregistration_verification_status')
        self.restaurant = Restaurant.objects.create(name='Verified tenant', active=True)
        self.unconfigured = Restaurant.objects.create(name='Missing setup tenant', active=True)
        self.opted_out = Restaurant.objects.create(
            name='Demo tenant', active=True, require_verified_orders=False,
        )
        self.android = NativeAppRegistration.objects.create(
            name='Android customer', platform='android', role='customer',
            restaurant=self.restaurant, app_id='no.blakken.customer',
            certificate_digests=[base64.urlsafe_b64encode(b'c' * 32).decode()],
            enabled=True,
        )
        self.ios = NativeAppRegistration.objects.create(
            name='iOS management', platform='ios', role='management',
            app_id='TEAM.no.blakken.management', enabled=True,
        )

    def test_requires_admin_and_both_app_configuration_and_restaurant_permissions(self):
        self.assertRedirects(
            self.client.get(self.url), f'{reverse("admin:login")}?next={self.url}',
        )
        staff = get_user_model().objects.create_user(username='staff', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        staff.user_permissions.add(Permission.objects.get(codename='view_nativeappregistration'))
        self.assertEqual(self.client.get(self.url).status_code, 403)
        staff.user_permissions.add(Permission.objects.get(codename='view_restaurant'))
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="action"')
        with patch('blakken.verification_status.check_google_credentials') as check:
            response = self.client.post(self.url, {'action': 'check_google_credentials'})
        self.assertEqual(response.status_code, 403)
        check.assert_not_called()

    def test_get_reports_local_gaps_and_policies_without_contacting_google(self):
        self.client.force_login(self.operator)
        with patch('blakken.verification_status.google.auth.default') as discover:
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        discover.assert_not_called()
        self.assertFalse(response.context['google_credentials']['checked'])
        self.assertIn('no-store', response['Cache-Control'])
        tenants = {row['restaurant'].pk: row for row in response.context['tenants']}
        self.assertTrue(tenants[self.restaurant.pk]['local_app_available'])
        self.assertFalse(tenants[self.unconfigured.pk]['local_app_available'])
        self.assertContains(response, 'Blocked: no customer app passes local configuration checks.')
        self.assertContains(response, 'Explicit opt-out: regular orders allowed.')
        self.assertContains(response, 'Management login/refresh policy:')
        self.assertContains(response, 'Play Console linking')
        self.assertContains(response, 'real-device integrity verdicts')
        self.assertContains(response, str(self.android.pk))

    def test_disabled_provider_invalid_digest_and_inactive_restaurant_show_action_required(self):
        self.android.certificate_digests = ['bad-digest']
        self.android.save()
        self.restaurant.active = False
        self.restaurant.save()
        self.client.force_login(self.operator)
        with override_settings(PLAY_INTEGRITY_ENABLED=False):
            response = self.client.get(self.url)
        row = next(row for row in response.context['apps'] if row['app'].pk == self.android.pk)
        self.assertFalse(row['local_ok'])
        failed = {check['label'] for check in row['checks'] if not check['ok']}
        self.assertIn('Play App Signing certificate digests configured', failed)
        self.assertIn('Play Integrity provider enabled', failed)
        self.assertIn('Restaurant active', failed)

    def test_explicit_credential_check_is_scoped_bounded_and_does_not_decode_tokens(self):
        self.client.force_login(self.operator)
        credentials = Mock(valid=True)
        credentials.refresh.side_effect = lambda request: request(
            url='https://oauth2.googleapis.com/token', timeout=100,
        )
        with patch(
            'blakken.verification_status.google.auth.default', return_value=(credentials, 'project'),
        ) as discover, patch('blakken.verification_status.Request') as transport, patch(
            'blakken.play_integrity.decode_integrity_token',
        ) as decode:
            response = self.client.post(self.url, {'action': 'check_google_credentials'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['google_credentials']['ok'])
        self.assertEqual(discover.call_args.kwargs['scopes'], [PLAY_INTEGRITY_SCOPE])
        self.assertEqual(transport.return_value.call_args.kwargs['timeout'], 5)
        decode.assert_not_called()
        self.assertContains(response, 'OAuth check passed.')
        self.assertContains(response, 'does not confirm Play Integrity API enablement')

    def test_credential_failures_never_render_exception_details_or_tokens(self):
        self.client.force_login(self.operator)
        secret_marker = 'test-secret-that-must-not-be-rendered'
        for error in (DefaultCredentialsError(secret_marker), RefreshError(secret_marker)):
            with self.subTest(error=type(error).__name__), patch(
                'blakken.verification_status.google.auth.default', side_effect=error,
            ):
                response = self.client.post(self.url, {'action': 'check_google_credentials'})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.context['google_credentials']['ok'])
            self.assertNotContains(response, secret_marker)
            self.assertContains(response, 'Could not obtain a Google OAuth access token.')

    def test_credential_check_preserves_csrf_and_never_mutates_app_configuration(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.operator)
        with patch(
            'blakken.verification_status.google.auth.default', return_value=(Mock(valid=True), None),
        ) as discover:
            blocked = client.post(self.url, {'action': 'check_google_credentials'})
            self.assertEqual(blocked.status_code, 403)
            discover.assert_not_called()
            client.get(self.url)
            response = client.post(
                self.url, {'action': 'check_google_credentials'},
                HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value,
            )
        self.assertEqual(response.status_code, 200)
        self.android.refresh_from_db()
        self.restaurant.refresh_from_db()
        self.assertTrue(self.android.enabled)
        self.assertTrue(self.restaurant.require_verified_orders)

    def test_changelist_links_to_status_and_app_names_are_escaped(self):
        self.client.force_login(self.operator)
        response = self.client.get(reverse('admin:blakken_nativeappregistration_changelist'))
        self.assertContains(response, self.url)
        self.android.name = '<script>alert("test")</script>'
        self.android.save()
        response = self.client.get(self.url)
        self.assertNotContains(response, '<script>alert("test")</script>')
        self.assertContains(response, '&lt;script&gt;')
