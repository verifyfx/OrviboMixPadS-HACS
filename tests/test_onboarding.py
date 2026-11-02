"""Synthetic panel-first onboarding; never contacts a real account or panel."""

import types
import unittest
from unittest.mock import AsyncMock, patch

from . import bootstrap  # noqa: F401
from custom_components.orvibo_mixpad.cloud import Snapshot
from custom_components.orvibo_mixpad.models import Relay
from custom_components.orvibo_mixpad.onboarding import identify_panel, import_panel
from custom_components.orvibo_mixpad.protocol import ProtocolError

FIRST = Relay("first-test-panel", "first-test-relay", 1, "First test light")
SECOND = Relay("second-test-panel", "second-test-relay", 0, "Second test light")
DATA = {"username": "synthetic-user", "password_hash": "SYNTHETIC-HASH",
        "topology": {"gateways": {}, "relays": []}}


def snapshot(hosts=None):
    return Snapshot({r.key: r for r in (FIRST, SECOND)}, hosts or {}, [], 1)


class OnboardingTests(unittest.IsolatedAsyncioTestCase):
    def fake(self, uid):
        return types.SimpleNamespace(peer_uid=uid, connect=AsyncMock(), close=AsyncMock())

    async def test_blank_uid_unique_cloud_ip_match(self):
        fake = self.fake(None)
        with patch("custom_components.orvibo_mixpad.onboarding.Gateway", return_value=fake):
            uid = await identify_panel("192.168.50.20", DATA, snapshot({FIRST.uid: "192.168.50.20"}))
        self.assertEqual(uid, FIRST.uid)
        fake.close.assert_awaited_once()

    async def test_stale_cloud_ip_uses_handshake_identity(self):
        with patch("custom_components.orvibo_mixpad.onboarding.Gateway", return_value=self.fake(FIRST.uid)):
            uid = await identify_panel("192.168.50.21", DATA, snapshot({FIRST.uid: "192.168.50.20"}))
        self.assertEqual(uid, FIRST.uid)

    async def test_blank_unknown_or_duplicate_cloud_ip_requires_selection(self):
        for hosts in ({}, {FIRST.uid: "192.168.50.20", SECOND.uid: "192.168.50.20"}):
            with patch("custom_components.orvibo_mixpad.onboarding.Gateway", return_value=self.fake(None)):
                self.assertIsNone(await identify_panel("192.168.50.20", DATA, snapshot(hosts)))

    async def test_conflicting_or_foreign_identity_never_guessed(self):
        for peer in (SECOND.uid, "not-in-account"):
            with patch("custom_components.orvibo_mixpad.onboarding.Gateway", return_value=self.fake(peer)):
                with self.assertRaises(ProtocolError):
                    await identify_panel("192.168.50.20", DATA, snapshot({FIRST.uid: "192.168.50.20"}))

    async def test_import_filters_to_panel_and_adds_another(self):
        topology, scope, rows = import_panel(DATA, snapshot(), FIRST.uid, "192.168.50.20")
        self.assertEqual(scope, [FIRST.uid])
        self.assertEqual(rows, [FIRST.as_row()])
        self.assertFalse(DATA["topology"]["gateways"])
        updated = dict(DATA, topology=topology)
        topology, scope, rows = import_panel(updated, snapshot(), SECOND.uid, "192.168.50.21", selected=scope)
        self.assertEqual(len(topology["gateways"]), 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(scope, [FIRST.uid, SECOND.uid])

    async def test_public_ip_rejected_before_connect(self):
        with patch("custom_components.orvibo_mixpad.onboarding.Gateway") as gateway:
            with self.assertRaises(ValueError):
                await identify_panel("8.8.8.8", DATA, snapshot())
            gateway.assert_not_called()
