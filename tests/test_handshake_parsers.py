import struct
import unittest

from top_100_proxy import (
    SOCKS4_GRANTED,
    SOCKS4_MAX_CODE,
    SOCKS4_REQUEST,
    SOCKS5_GREETING,
    SOCKS5_NO_ACCEPTABLE_METHODS,
    SOCKS5_NO_AUTH,
    parse_socks4_reply,
    parse_socks5_reply,
)


class ParseSocks5ReplyTest(unittest.TestCase):
    def test_accepts_no_auth(self):
        self.assertEqual(parse_socks5_reply(b'\x05\x00'), SOCKS5_NO_AUTH)

    def test_reports_auth_required(self):
        self.assertEqual(parse_socks5_reply(b'\x05\xff'), SOCKS5_NO_ACCEPTABLE_METHODS)

    def test_rejects_wrong_version(self):
        self.assertIsNone(parse_socks5_reply(b'\x04\x00'))

    def test_rejects_empty_and_none(self):
        self.assertIsNone(parse_socks5_reply(b''))
        self.assertIsNone(parse_socks5_reply(None))

    def test_rejects_truncated(self):
        self.assertIsNone(parse_socks5_reply(b'\x05'))

    def test_accepts_extra_trailing_bytes(self):
        self.assertEqual(parse_socks5_reply(b'\x05\x00\x00\x00'), SOCKS5_NO_AUTH)


class ParseSocks4ReplyTest(unittest.TestCase):
    def test_accepts_granted(self):
        self.assertEqual(parse_socks4_reply(b'\x00\x5a'), SOCKS4_GRANTED)

    def test_accepts_rejected_as_alive(self):
        self.assertEqual(parse_socks4_reply(b'\x00\x5b'), 0x5B)

    def test_accepts_upper_bound_code(self):
        self.assertEqual(parse_socks4_reply(b'\x00\x5f'), SOCKS4_MAX_CODE)

    def test_rejects_code_above_range(self):
        self.assertIsNone(parse_socks4_reply(b'\x00\x60'))

    def test_rejects_code_below_range(self):
        self.assertIsNone(parse_socks4_reply(b'\x00\x59'))

    def test_rejects_wrong_version(self):
        self.assertIsNone(parse_socks4_reply(b'\x05\x5a'))

    def test_rejects_empty_and_none(self):
        self.assertIsNone(parse_socks4_reply(b''))
        self.assertIsNone(parse_socks4_reply(None))

    def test_rejects_truncated(self):
        self.assertIsNone(parse_socks4_reply(b'\x00'))


class RequestConstantsTest(unittest.TestCase):
    def test_socks4_request_layout(self):
        self.assertEqual(SOCKS4_REQUEST, b'\x04\x01\x00\x50\xc0\x00\x02\x01\x00')
        self.assertEqual(len(SOCKS4_REQUEST), 9)
        self.assertEqual(SOCKS4_REQUEST[0], 0x04)
        self.assertEqual(SOCKS4_REQUEST[1], 0x01)
        self.assertEqual(struct.unpack('>H', SOCKS4_REQUEST[2:4])[0], 80)
        self.assertEqual(SOCKS4_REQUEST[4:8], bytes((192, 0, 2, 1)))
        self.assertEqual(SOCKS4_REQUEST[8:], b'\x00')

    def test_socks5_greeting_offers_only_no_auth(self):
        self.assertEqual(SOCKS5_GREETING, b'\x05\x01\x00')


if __name__ == '__main__':
    unittest.main()
