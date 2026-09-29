from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse


class LandingViewTests(TestCase):
    def setUp(self):
        self.url = reverse('landing')

    def test_anonymous_sees_signup_and_login(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Get started')
        self.assertContains(response, reverse('signup'))
        self.assertNotContains(response, reverse('dashboard'))

    def test_homeowner_sees_dashboard_link_not_signup(self):
        user = User.objects.create_user('alice', password='pw')
        user.groups.add(Group.objects.get(name='homeowner'))
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertContains(response, 'Welcome back, alice')
        self.assertContains(response, reverse('dashboard'))
        self.assertNotContains(response, 'Get started')
        self.assertNotContains(response, reverse('signup'))

    def test_non_homeowner_gets_no_dashboard_link(self):
        user = User.objects.create_superuser('admin', password='pw')
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertContains(response, 'Welcome back, admin')
        self.assertNotContains(response, reverse('dashboard'))
        self.assertContains(response, reverse('admin:index'))
