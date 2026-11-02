"""Read-only account snapshots, shared tokens, global pacing and bounded backoff."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import math
import random
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from .models import Relay, inventory

SIGN_KEY = "nQ45RjPtOws96jmH"


class CloudError(Exception):
    """Sanitized cloud failure, never includes response bodies or credentials."""


class CloudAuthError(CloudError):
    """Login rejected; reauthentication required."""


class ApiRejected(CloudError):
    """Application error; may indicate expired token, renew at most once."""


def password_digest(password):
    return hashlib.md5(password.encode(), usedforsecurity=False).hexdigest().upper()


def signed(params):
    message = "".join(f"{k}={params[k]}&" for k in sorted(params)
                      if params[k] is not None and str(params[k]).strip()) + "key=" + SIGN_KEY
    return dict(params, sign=hmac.new(SIGN_KEY.encode(), message.encode(), hashlib.sha256).hexdigest().upper())


def retry_after(value):
    try:
        seconds = float(value)
        return seconds if math.isfinite(seconds) and seconds >= 0 else 60.0
    except (TypeError, ValueError):
        try:
            return max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return 60.0


class RequestGate:
    """One integration-wide queue across setup flows and all accounts."""

    def __init__(self, spacing=2):
        self.lock = asyncio.Lock()
        self.spacing = spacing
        self.next_request = self.blocked_until = 0.0

    async def request(self, transport, path, params, form=False):
        async with self.lock:
            if time.monotonic() < self.blocked_until:
                raise CloudError("Cloud requests paused after rate limiting")
            await asyncio.sleep(max(0, self.next_request - time.monotonic()))
            self.next_request = time.monotonic() + self.spacing
            try:
                status, headers, body = await transport(path, params, form)
            except (OSError, TimeoutError, ValueError):
                raise CloudError("Cloud transport failed") from None
            if status == 429:
                self.blocked_until = time.monotonic() + max(60, retry_after(headers.get("Retry-After")))
                raise CloudError("Cloud rate limited; retry deferred")
            if status in (401, 403):
                if form:
                    raise CloudAuthError("Cloud login rejected")
                raise ApiRejected("Cloud session rejected")
            if status != 200 or not isinstance(body, dict):
                raise CloudError("Cloud HTTP or schema failure")
            if body.get("code", body.get("status")) != 0:
                if form:
                    raise CloudAuthError("Cloud login rejected")
                raise ApiRejected("Cloud API rejected request")
            return body


@dataclass
class Snapshot:
    relays: dict
    hosts: dict
    statuses: list
    started: float
    # App and upstream implement page0 only. No proof that page0 exhausts a large home.
    complete: bool = False
    observed_devices: dict | None = None


class CloudAccount:
    def __init__(self, username, password_hash, gate, transport, *, jitter=lambda: random.uniform(5, 20)):
        self.username, self.password_hash = username, password_hash
        self.gate, self.transport, self.jitter = gate, transport, jitter
        self.token = self.user_id = None
        self.expires = 0
        self.cached = self.task = None
        self.cached_at = self.retry_at = 0
        self.failures = 0
        self.auth_failed = False

    def _params(self):
        return {"accessToken": self.token, "userId": self.user_id,
                "random": secrets.token_hex(16), "timestamp": int(time.time() * 1000)}

    async def _request(self, path, params, form=False):
        return await self.gate.request(self.transport, path, params if form else signed(params), form)

    async def _login(self):
        result = await self._request("/getOauthToken", {"userName": self.username,
                                                      "password": self.password_hash, "type": "0"}, True)
        data = result.get("data")
        if (not isinstance(data, dict) or not isinstance(data.get("access_token"), str)
                or not data["access_token"] or not data.get("user_id")):
            raise CloudError("Cloud login response incomplete")
        self.token, self.user_id = data["access_token"], data["user_id"]
        try:
            ttl = float(data.get("expires_in", 1800))
        except (TypeError, ValueError):
            ttl = 1800
        if not math.isfinite(ttl):
            ttl = 1800
        self.expires = time.monotonic() + max(1, min(1800, ttl - 60))

    async def refresh(self):
        if self.auth_failed:
            raise CloudAuthError("Cloud reauthentication required")
        if self.task and not self.task.done():
            return await asyncio.shield(self.task)
        if self.cached and time.monotonic() - self.cached_at < 60:
            return self.cached
        if time.monotonic() < self.retry_at:
            raise CloudError("Cloud refresh is in backoff")
        self.task = asyncio.create_task(self._refresh())
        # Retrieve errors even if all callers are cancelled while shielded.
        self.task.add_done_callback(lambda t: None if t.cancelled() else t.exception())
        return await asyncio.shield(self.task)

    async def _refresh(self):
        try:
            if self.cached is None:
                await asyncio.sleep(self.jitter())
            started = time.monotonic()
            for attempt in range(2):
                if not self.token or time.monotonic() >= self.expires:
                    await self._login()
                try:
                    snapshot = await self._inventory(started)
                    break
                except ApiRejected:
                    self.token = self.user_id = None
                    if attempt:
                        # Unknown API errors must not be mislabeled bad credentials.
                        raise CloudError("Cloud API rejected refreshed session") from None
            self.cached, self.cached_at = snapshot, time.monotonic()
            self.failures = 0
            self.retry_at = 0
            return snapshot
        except CloudAuthError:
            self.auth_failed = True
            self.token = self.user_id = None
            raise
        except (CloudError, ValueError, TypeError, KeyError):
            self.failures += 1
            self.retry_at = time.monotonic() + min(3600, 60 * 2 ** min(6, self.failures - 1))
            raise CloudError("Cloud snapshot unavailable; retry deferred") from None

    async def _inventory(self, started):
        result = await self._request("/v2/family/statistics/users", self._params())
        families = result.get("data")
        if isinstance(families, dict):
            families = families.get("familyInfo")
        if not isinstance(families, list) or len(families) > 100:
            raise CloudError("Invalid or excessive family list")
        ids = []
        for row in families:
            if not isinstance(row, dict) or not isinstance(row.get("familyId"), str) or not row["familyId"]:
                raise CloudError("Invalid family row")
            if row["familyId"] not in ids:
                ids.append(row["familyId"])
        relays, hosts, statuses, observed = {}, {}, [], {}
        for family in ids:
            params = dict(self._params(), familyId=family, dataType="all", deviceFlag=0,
                          lastUpdateTime=0, pageIndex=0, serial=secrets.randbelow(1000000000),
                          sessionId="", userName=self.username, ver="5.2.6.308")
            result = await self._request("/v2/cmd/app/readtable", params)
            data = result.get("data")
            # No invented continuation contract. Fail atomically when a server announces
            # pagination we cannot yet validate; never replace topology with partial data.
            if not isinstance(data, dict):
                raise CloudError("Invalid readtable data")
            if any(data.get(k) for k in ("hasNext", "nextPage", "nextPageIndex")) or data.get("pageCount", 1) != 1:
                raise CloudError("Server pagination requires protocol verification")
            family_relays, family_hosts = inventory(data)
            relays.update(family_relays)
            hosts.update(family_hosts)
            statuses.extend(data.get("deviceStatus", []))
            for row in data.get("device", []):
                if (not isinstance(row.get("uid"), str) or not row["uid"]
                        or not isinstance(row.get("deviceId"), str) or not row["deviceId"]
                        or type(row.get("deviceType")) is not int):
                    continue
                pair = (row["uid"], row["deviceId"])
                if row["deviceType"] != 1:
                    observed.setdefault(pair, set())
                else:
                    try:
                        relay = Relay.from_row(row)
                    except ValueError:
                        continue
                    observed.setdefault(pair, set()).add(relay.key)
        return Snapshot(relays, hosts, statuses, started, observed_devices=observed)

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.token = self.user_id = self.cached = None
