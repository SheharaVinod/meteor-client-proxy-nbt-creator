import io
import os
import tempfile
import unittest
from pathlib import Path

import nbtlib
from nbtlib.tag import Compound, List

from main import build_proxy, build_root

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_PATH = PROJECT_ROOT / "sorce" / "proxies.nbt"
CSV_PATH = PROJECT_ROOT / "sorce" / "data.csv"


def load_reference():
    return nbtlib.load(str(REFERENCE_PATH))


def encode(tag):
    buffer = io.BytesIO()
    nbtlib.File(Compound({'_': tag}), gzipped=False).write(buffer)
    return buffer.getvalue()


def schema(tag):
    if isinstance(tag, List):
        return ['List', [schema(item) for item in tag]]
    if isinstance(tag, Compound):
        return {str(key): schema(value) for key, value in tag.items()}
    return type(tag).__name__


class BuildProxyStructureTest(unittest.TestCase):
    def setUp(self):
        self.reference = load_reference()
        self.by_name = {}
        for proxy in self.reference['proxies']:
            settings = proxy['settings']['groups'][0]['settings']
            values = {str(entry['name']): entry['value'] for entry in settings}
            self.by_name[str(values['name'])] = proxy

    @staticmethod
    def _names(proxy):
        settings = proxy['settings']['groups'][0]['settings']
        return [str(entry['name']) for entry in settings]

    def test_socks5_proxy_is_byte_identical_to_reference(self):
        ours = build_proxy('US 1 Cincinnati', 'socks5', '69.61.200.104', 36181)
        self.assertEqual(encode(ours), encode(self.by_name['US 1 Cincinnati']))

    def test_socks4_proxy_is_byte_identical_to_reference(self):
        ours = build_proxy('TH 1 Sing Buri', 'socks4', '1.4.195.114', 4145)
        self.assertEqual(encode(ours), encode(self.by_name['TH 1 Sing Buri']))

    def test_root_has_proxies_then_empty_settings(self):
        root = build_root(List[Compound]())
        self.assertEqual(list(root.keys()), ['proxies', 'settings'])
        self.assertEqual(len(root['proxies']), 0)
        self.assertEqual(len(root['settings']), 0)
        self.assertIsInstance(root['settings'], Compound)
        self.assertEqual(list(load_reference().keys()), ['proxies', 'settings'])

    def test_every_reference_proxy_matches_our_deep_schema(self):
        with_type = [proxy for proxy in self.reference['proxies']
                     if 'type' in self._names(proxy)]
        without_type = [proxy for proxy in self.reference['proxies']
                        if 'type' not in self._names(proxy)]

        self.assertEqual(len(with_type), 2)
        self.assertEqual(len(without_type), 6)

        socks4 = build_proxy('X 1 Y', 'socks4', '1.2.3.4', 1080)
        socks5 = build_proxy('X 1 Y', 'socks5', '1.2.3.4', 1080)

        self.assertTrue(all(schema(socks4) == schema(proxy) for proxy in with_type))
        self.assertTrue(all(schema(socks5) == schema(proxy) for proxy in without_type))
        self.assertNotEqual(schema(socks4), schema(socks5))


class MainEndToEndTest(unittest.TestCase):
    def test_full_csv_conversion_matches_expected_sequence(self):
        import csv as csv_module
        import re

        from main import convert_csv_to_proxies_nbt

        pattern = re.compile(r'^(socks4|socks5)://([^:/]+):(\d+)$', re.IGNORECASE)
        expected = []
        grouped = {}
        with open(str(CSV_PATH), mode='r', encoding='utf-8', newline='') as csv_file:
            for row in csv_module.reader(csv_file):
                if not row or len(row) < 3:
                    continue
                match = pattern.match(row[0].strip())
                if match is None:
                    continue
                grouped.setdefault(row[1].strip().upper(), []).append(
                    (match.group(2), int(match.group(3)), row[2].strip()))

        for country in sorted(grouped):
            for index, (address, port, city) in enumerate(grouped[country], start=1):
                expected.append((f'{country} {index} {city}', address, port))

        with tempfile.TemporaryDirectory() as directory:
            output = os.path.join(directory, 'proxies.nbt')
            convert_csv_to_proxies_nbt(str(CSV_PATH), output)

            with open(output, 'rb') as handle:
                self.assertNotEqual(handle.read(2), b'\x1f\x8b')

            produced = nbtlib.load(output)

        actual = []
        for proxy in produced['proxies']:
            settings = proxy['settings']['groups'][0]['settings']
            values = {str(entry['name']): entry['value'] for entry in settings}
            actual.append((str(values['name']), str(values['address']), int(values['port'])))

        self.assertEqual(actual, expected)
        self.assertEqual(len(produced['settings']), 0)


if __name__ == '__main__':
    unittest.main()
