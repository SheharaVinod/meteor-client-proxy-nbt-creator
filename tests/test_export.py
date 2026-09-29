import io
import json
import os
import tempfile
import unittest

import nbtlib
from nbtlib.tag import Byte, Compound, Int, List, String

from top_100_proxy import build_proxies_list, save_proxies_nbt


def result(latency, country='LK', city='Sigiriya', address='1.1.1.1', port=1080,
           protocol='socks5'):
    return {
        'address': address,
        'port': port,
        'country': country,
        'city': city,
        'protocol': protocol,
        'latency': latency,
    }


def schema(tag):
    if isinstance(tag, List):
        return ['List', [schema(item) for item in tag]]
    if isinstance(tag, Compound):
        return {str(key): schema(value) for key, value in tag.items()}
    return type(tag).__name__


def settings_of(proxy):
    return proxy['settings']['groups'][0]['settings']


class BuildProxiesListTest(unittest.TestCase):
    def test_name_contains_global_rank_country_city_and_latency(self):
        proxies = build_proxies_list([
            result(45.0, country='LK', city='Sigiriya'),
            result(12.0, country='US', city='Cincinnati'),
        ])
        names = [str(settings_of(proxy)[0]['value']) for proxy in proxies]
        self.assertEqual(names, ['LK 1 Sigiriya (45ms)', 'US 2 Cincinnati (12ms)'])

    def test_latency_is_rounded_to_whole_milliseconds(self):
        proxies = build_proxies_list([result(45.6)])
        self.assertEqual(str(settings_of(proxies[0])[0]['value']), 'LK 1 Sigiriya (46ms)')

    def test_socks4_gets_type_setting_and_socks5_does_not(self):
        proxies = build_proxies_list([result(10.0, protocol='socks5'),
                                      result(20.0, protocol='socks4')])
        socks5_names = [str(entry['name']) for entry in settings_of(proxies[0])]
        socks4_names = [str(entry['name']) for entry in settings_of(proxies[1])]
        self.assertNotIn('type', socks5_names)
        self.assertIn('type', socks4_names)
        self.assertEqual([str(entry['value']) for entry in settings_of(proxies[1])
                          if str(entry['name']) == 'type'], ['Socks4'])

    def test_setting_entries_are_value_then_name(self):
        proxies = build_proxies_list([result(10.0)])
        for entry in settings_of(proxies[0]):
            self.assertEqual(list(entry.keys()), ['value', 'name'])

    def test_tag_types_match_meteor_reference(self):
        proxies = build_proxies_list([result(10.0, protocol='socks4')])
        entries = settings_of(proxies[0])
        by_name = {str(entry['name']): entry['value'] for entry in entries}
        self.assertIsInstance(by_name['name'], String)
        self.assertIsInstance(by_name['address'], String)
        self.assertIsInstance(by_name['type'], String)
        self.assertIsInstance(by_name['port'], Int)
        self.assertIsInstance(by_name['enabled'], Byte)
        self.assertEqual(int(by_name['enabled']), 0)
        group = proxies[0]['settings']['groups'][0]
        self.assertIsInstance(group['sectionExpanded'], Byte)
        self.assertEqual(int(group['sectionExpanded']), 1)
        self.assertIsInstance(group['name'], String)
        self.assertEqual(str(group['name']), 'General')


class SaveProxiesNbtTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, 'top_100.nbt')

    def test_writes_uncompressed_file_with_matching_structure(self):
        reference = nbtlib.load('sorce/proxies.nbt')
        selected = [result(45.0), result(12.0, protocol='socks4')]
        save_proxies_nbt(selected, self.path)

        with open(self.path, 'rb') as handle:
            raw = handle.read()
        self.assertNotEqual(raw[:2], b'\x1f\x8b')
        self.assertEqual(raw[:3], b'\x0a\x00\x00')

        produced = nbtlib.load(self.path)
        self.assertEqual(list(produced.keys()), ['proxies', 'settings'])
        self.assertEqual(len(produced['settings']), 0)
        self.assertEqual(len(produced['proxies']), 2)
        self.assertEqual(json.dumps(schema(produced['proxies'][0]), sort_keys=True),
                         json.dumps(schema(reference['proxies'][0]), sort_keys=True))
        self.assertEqual(json.dumps(schema(produced['proxies'][1]), sort_keys=True),
                         json.dumps(schema(reference['proxies'][6]), sort_keys=True))

    def test_handles_empty_selection(self):
        save_proxies_nbt([], self.path)
        produced = nbtlib.load(self.path)
        self.assertEqual(len(produced['proxies']), 0)
        self.assertEqual(len(produced['settings']), 0)


if __name__ == '__main__':
    unittest.main()
