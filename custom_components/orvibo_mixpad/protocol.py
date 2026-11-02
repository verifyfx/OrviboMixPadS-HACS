"""Independent framed MixPad protocol, informed by orvibo-lan-control (MIT)."""

import json
import struct
import zlib

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

DEFAULT_KEY = b"khggd54865SNJHGF"
EMPTY_SESSION = b" " * 32


class ProtocolError(Exception):
    """Sanitized local protocol failure."""


class AuthenticationError(ProtocolError):
    """Account credentials rejected."""


def encode(payload, key=DEFAULT_KEY, session=EMPTY_SESSION, kind=b"pk"):
    if len(session) != 32 or kind not in (b"pk", b"dk"):
        raise ProtocolError("Invalid session or packet kind")
    padder = padding.PKCS7(128).padder()
    plain = json.dumps(payload, separators=(",", ":")).encode()
    padded = padder.update(plain) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    body = cipher.update(padded) + cipher.finalize()
    if len(body) + 42 > 65535:
        raise ProtocolError("Packet too long")
    return b"hd" + struct.pack(">H", len(body) + 42) + kind + struct.pack(">I", zlib.crc32(body)) + session + body


def decode(frame, session=EMPTY_SESSION, key=DEFAULT_KEY, *, bootstrap=False):
    if len(frame) < 58 or frame[:2] != b"hd" or int.from_bytes(frame[2:4], "big") != len(frame):
        raise ProtocolError("Invalid frame")
    body = frame[42:]
    if len(body) % 16 or zlib.crc32(body) != int.from_bytes(frame[6:10], "big"):
        raise ProtocolError("Invalid ciphertext checksum")
    if frame[4:6] == b"pk" and bootstrap:
        aes_key = DEFAULT_KEY
    elif frame[4:6] == b"dk" and frame[10:42] == session and not bootstrap:
        aes_key = key
    else:
        raise ProtocolError("Unexpected packet kind or session")
    try:
        cipher = Cipher(algorithms.AES(aes_key), modes.ECB()).decryptor()
        padded = cipher.update(body) + cipher.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        value = json.loads(unpadder.update(padded) + unpadder.finalize())
    except (ValueError, UnicodeError):
        raise ProtocolError("Invalid encrypted JSON") from None
    if not isinstance(value, dict):
        raise ProtocolError("Expected JSON object")
    return value
