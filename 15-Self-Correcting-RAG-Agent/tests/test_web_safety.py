"""URL safety allowlist for the web fetch step: scheme, private IP, localhost.
Uses literal IPs (and the "localhost" special case) so no real DNS/network
access is needed -- only the "allowed" case monkeypatches socket.getaddrinfo.
"""

import socket

import pytest

from self_correcting_rag.web.safety import UnsafeUrlError, assert_safe_url


def test_localhost_is_blocked():
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("http://localhost/secret")


def test_loopback_ip_is_blocked():
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("http://127.0.0.1:8080/admin")


def test_private_ip_is_blocked():
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("http://192.168.1.1/")


def test_link_local_ip_is_blocked():
    # The AWS/GCP cloud metadata endpoint address -- a classic SSRF target.
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("http://169.254.169.254/latest/meta-data/")


def test_disallowed_scheme_is_blocked():
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("file:///etc/passwd")


def test_public_ip_is_allowed(monkeypatch):
    def fake_getaddrinfo(host, port):
        assert host == "safe.example.test"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert_safe_url("https://safe.example.test/page")  # does not raise
