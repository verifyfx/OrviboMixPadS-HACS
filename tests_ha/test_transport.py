"""Credential-bearing HTTP must be bounded, POST-only and nonredirecting."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.orvibo_mixpad.cloud import CloudError
from custom_components.orvibo_mixpad.transport import make_transport


def session_response(status, chunks):
    async def content():
        for chunk in chunks:
            yield chunk
    response = MagicMock(status=status, headers={})
    response.content.iter_chunked.return_value = content()
    context = AsyncMock()
    context.__aenter__.return_value = response
    session = MagicMock()
    session.post.return_value = context
    return session, response


async def test_redirect_refused_and_password_stays_in_post_body():
    session, response = session_response(302, [])
    transport = make_transport(session, "usa.orvibo.com")
    credentials = {"password": "SYNTHETIC-HASH"}
    status, _, body = await transport("/getOauthToken", credentials, True)
    assert status == 302
    assert body is None
    args, kwargs = session.post.call_args
    assert args[0] == "https://usa.orvibo.com/getOauthToken"
    assert kwargs["data"] == credentials
    assert kwargs["allow_redirects"] is False
    assert "params" not in kwargs
    response.content.iter_chunked.assert_not_called()


async def test_response_size_limit(monkeypatch):
    monkeypatch.setattr("custom_components.orvibo_mixpad.transport.MAX_RESPONSE", 8)
    session, _ = session_response(200, [b"12345", b"67890"])
    with pytest.raises(CloudError, match="too large"):
        await make_transport(session, "usa.orvibo.com")("/getOauthToken", {}, True)


async def test_bad_json_sanitized_and_custom_hosts_rejected():
    session, _ = session_response(200, [b"private-response-not-json"])
    with pytest.raises(CloudError) as caught:
        await make_transport(session, "usa.orvibo.com")("/getOauthToken", {}, True)
    assert "private-response" not in str(caught.value)
    with pytest.raises(ValueError):
        make_transport(session, "us.orvibo.com")
