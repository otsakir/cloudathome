from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
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


class CloudserverUrlTests(TestCase):
    """cloudserver_url() is what homes pass as cah.py's --cloudserver-url."""

    def setUp(self):
        from django.test import RequestFactory
        self.request = RequestFactory().get('/', HTTP_HOST='203.0.113.5:8080')

    def url(self, https):
        from unittest.mock import patch
        from web.services import cloudserver_url
        with patch('web.services.HAProxyService.https_available', return_value=https):
            return cloudserver_url(self.request)

    @override_settings(CAH_HOSTNAME='cloud.example.com', CAH_HTTP_PORT=80, CAH_HTTPS_PORT=443)
    def test_standard_ports_are_omitted(self):
        self.assertEqual(self.url(https=False), 'http://cloud.example.com')
        self.assertEqual(self.url(https=True), 'https://cloud.example.com')

    @override_settings(CAH_HOSTNAME='cloud.example.com', CAH_HTTP_PORT=8080, CAH_HTTPS_PORT=8443)
    def test_non_standard_ports_are_included(self):
        self.assertEqual(self.url(https=False), 'http://cloud.example.com:8080')
        self.assertEqual(self.url(https=True), 'https://cloud.example.com:8443')

    @override_settings(CAH_HOSTNAME=None, ALLOWED_HOSTS=['203.0.113.5'])
    def test_falls_back_to_request_host_without_cah_hostname(self):
        self.assertEqual(self.url(https=False), 'http://203.0.113.5:8080')


@override_settings(CAH_HOSTNAME='cloud.example.com', CAH_HTTP_PORT=80, CAH_SSH_PORT=8022,
                   ALLOWED_HOSTS=['cloud.example.com'])
class ConnectionDetailsTests(TestCase):
    def setUp(self):
        from unittest.mock import patch
        patcher = patch('web.services.HAProxyService.https_available', return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = User.objects.create_user('alice', password='pw')
        self.user.groups.add(Group.objects.get(name='homeowner'))
        self.client.force_login(self.user)

    def test_dashboard_shows_cloudserver_url_without_home(self):
        response = self.client.get(reverse('dashboard'), HTTP_HOST='cloud.example.com')
        self.assertContains(response, 'Cloud server URL')
        self.assertContains(response, '--cloudserver-url http://cloud.example.com --token')

    def test_token_page_shows_ready_to_paste_register_command(self):
        response = self.client.post(reverse('rotate_token'), HTTP_HOST='cloud.example.com')
        token = response.context['token']
        self.assertContains(response, f'--cloudserver-url http://cloud.example.com --token {token}')


@override_settings(CAH_HOSTNAME='cloud.example.com', CAH_HTTP_PORT=80, CAH_SSH_PORT=8022,
                   ALLOWED_HOSTS=['cloud.example.com'])
class DashboardTunnelPortsTests(TestCase):
    def setUp(self):
        from unittest.mock import patch
        from core.models import Home
        from core.ssh.manage_home import tunnel_manager
        patcher = patch('web.services.HAProxyService.https_available', return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = User.objects.create_user('alice', password='pw')
        self.user.groups.add(Group.objects.get(name='homeowner'))
        self.client.force_login(self.user)
        Home.objects.filter(home_index=0).update(user=self.user, slug='s')
        self.config = tunnel_manager.config
        self.port_base = tunnel_manager.get_home_port_base(0)
        self.tcp_base = tunnel_manager.get_home_tcp_public_port_base(0)
        self.other_port_base = tunnel_manager.get_home_port_base(1)

    def get_dashboard(self, entries):
        from unittest.mock import patch
        with patch('core.services.HAProxyService.dump_mappings', return_value=entries):
            return self.client.get(reverse('dashboard'), HTTP_HOST='cloud.example.com')

    def test_shows_range_and_usage_breakdown(self):
        b = self.port_base
        response = self.get_dashboard([
            {'host': 'a.example.com', 'public_port': 443, 'backend': f'tunnel_{b}', 'scheme': 'https'},
            {'host': 'a.example.com', 'public_port': 80, 'backend': f'http_tunnel_{b + 1}', 'scheme': 'http'},
            {'public_port': self.tcp_base, 'backend': f'tunnel_{b + 2}', 'scheme': 'tcp'},
            {'host': 'b.example.com', 'public_port': 443, 'backend': f'tunnel_{self.other_port_base}', 'scheme': 'https'},
        ])
        last = b + self.config.TUNNEL_PORTS_PER_HOME - 1
        self.assertContains(
            response,
            f'{b}–{last} (3 of {self.config.TUNNEL_PORTS_PER_HOME} in use: 2 http/https, 1 tcp)',
        )

    def test_shows_zero_usage_without_breakdown(self):
        response = self.get_dashboard([])
        self.assertContains(response, f'(0 of {self.config.TUNNEL_PORTS_PER_HOME} in use)')
