"""HA-owned aiohttp session transport, validated HTTPS and no redirects."""

import json

from .cloud import CloudError
from .const import CLOUD_HOSTS

MAX_RESPONSE = 8 * 1024 * 1024


def make_transport(session, host):
    import aiohttp

    if host not in CLOUD_HOSTS:
        raise ValueError("Unsupported cloud server")

    async def transport(path, params, form):
        if path not in ("/getOauthToken", "/v2/family/statistics/users", "/v2/cmd/app/readtable"):
            raise CloudError("Unsupported cloud operation")
        try:
            async with session.post(
                f"https://{host}{path}", **({"data": params} if form else {"json": params}),
                allow_redirects=False, timeout=aiohttp.ClientTimeout(total=30, connect=10),
            ) as response:
                if response.status != 200:
                    return response.status, response.headers, None
                body = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE:
                        raise CloudError("Cloud response too large")
                try:
                    value = json.loads(body)
                except (ValueError, UnicodeError):
                    raise CloudError("Cloud response invalid") from None
                return response.status, response.headers, value
        except (aiohttp.ClientError, OSError, TimeoutError):
            raise CloudError("Cloud transport failed") from None

    return transport
