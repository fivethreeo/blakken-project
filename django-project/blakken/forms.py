from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from .models import Restaurant, RestaurantMembership, ShopStatus


class RestaurantRegistrationForm(forms.Form):
    restaurant_name = forms.CharField(max_length=150, label=_('Restaurant name'))
    email = forms.EmailField(max_length=150, label=_('Email address'))
    password = forms.CharField(widget=forms.PasswordInput, label=_('Password'))
    password_confirm = forms.CharField(
        widget=forms.PasswordInput, label=_('Confirm password'),
    )

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        user_model = get_user_model()
        if user_model._default_manager.filter(email__iexact=email).exists():
            raise forms.ValidationError(_('An account already uses this email address.'))
        if user_model._default_manager.filter(username__iexact=email).exists():
            raise forms.ValidationError(_('An account already uses this email address.'))
        return email

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('password')
        password_confirm = cleaned.get('password_confirm')
        if password and password_confirm and password != password_confirm:
            self.add_error('password_confirm', _('The passwords do not match.'))
        if password and 'email' in cleaned:
            user = get_user_model()(username=cleaned['email'], email=cleaned['email'])
            try:
                validate_password(password, user)
            except ValidationError as error:
                self.add_error('password', error)
        return cleaned

    @transaction.atomic
    def save(self):
        user_model = get_user_model()
        email = self.cleaned_data['email']
        user = user_model._default_manager.create_user(
            username=email,
            email=email,
            password=self.cleaned_data['password'],
        )
        restaurant = Restaurant.objects.create(
            name=self.cleaned_data['restaurant_name'].strip(),
            active=False,
        )
        RestaurantMembership.objects.create(
            user=user,
            restaurant=restaurant,
            role=RestaurantMembership.Role.OWNER,
        )
        ShopStatus.objects.create(restaurant=restaurant)
        return user, restaurant
