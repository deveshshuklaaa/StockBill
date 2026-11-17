"""Login throttling keyed on the real client address behind Cloudflare.

Production chain: client -> Cloudflare -> cloudflared -> nginx -> Gunicorn.
Django's REMOTE_ADDR is always nginx's container address, so DRF's default
key would put every user in one bucket: one person's failed logins would
lock everybody out.

Cloudflare sets CF-Connecting-IP to the address that connected to it and
overwrites any value a client sends. nginx forwards it only on the
listener that just cloudflared can reach and strips it on the loopback
listener (see deploy/nginx/stockbill.conf). With TRUST_CF_CONNECTING_IP=true
that header is the throttle key; otherwise (dev, shop PC) it is ignored and
DRF's normal REMOTE_ADDR/NUM_PROXIES logic applies.
"""

import ipaddress

from django.conf import settings
from rest_framework.throttling import ScopedRateThrottle


def cloudflare_client_ip(request):
    """The validated CF-Connecting-IP address, or None if absent/invalid."""
    raw = request.META.get("HTTP_CF_CONNECTING_IP", "").strip()
    if not raw:
        return None
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


class LoginRateThrottle(ScopedRateThrottle):
    def get_ident(self, request):
        if getattr(settings, "TRUST_CF_CONNECTING_IP", False):
            client_ip = cloudflare_client_ip(request)
            if client_ip:
                return client_ip
        return super().get_ident(request)
