import unittest

from . import bootstrap  # noqa: F401
from custom_components.orvibo_mixpad.discovery import Discovery, request_packet
from custom_components.orvibo_mixpad.protocol import decode, encode


class DiscoveryTests(unittest.TestCase):
    def test_upstream_request_format(self):
        message = decode(request_packet(), bootstrap=True)
        self.assertEqual(message["cmd"], 86)
        self.assertEqual(message["serial"], message["uniSerial"])

    def test_known_uid_lan_crc_and_conflicts(self):
        discovery = Discovery({"test-gateway"})
        packet = encode({"uid": "test-gateway"})
        for value, addr in ((packet, ("8.8.8.8", 10000)), (b"bad", ("192.168.1.5", 10000)),
                            (encode({"uid": "other"}), ("192.168.1.5", 10000))):
            discovery.datagram_received(value, addr)
        self.assertEqual(discovery.candidates, {})
        discovery.datagram_received(packet, ("192.168.1.5", 10000))
        self.assertEqual(discovery.candidates, {"test-gateway": "192.168.1.5"})
        discovery.datagram_received(packet, ("192.168.1.6", 10000))
        self.assertIn("test-gateway", discovery.conflicts)
