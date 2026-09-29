import os
import tempfile
import unittest

from top_100_proxy import read_endpoints

SAMPLE = (
    'socks5://1.1.1.1:1080,US,Ashburn\n'
    'socks4://2.2.2.2:4145,DE,Berlin\n'
    'http://3.3.3.3:8080,US,Nowhere\n'
    'socks5://1.1.1.1:1080,US,Ashburn\n'
    'socks4://1.1.1.1:1080,US,Ashburn\n'
    'socks5://4.4.4.4:9050,us,miami\n'
    'socks5://9.9.9.9:1080,US\n'
    '\n'
)


class ReadEndpointsTest(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False,
                                             encoding='utf-8')
        handle.write(SAMPLE)
        handle.close()
        self.path = handle.name

    def tearDown(self):
        os.unlink(self.path)

    def test_dedupes_by_host_and_port(self):
        endpoints = read_endpoints(self.path)
        self.assertEqual(len(endpoints), 3)

    def test_merges_protocols_for_duplicate_endpoint(self):
        endpoints = read_endpoints(self.path)
        self.assertIn(('1.1.1.1', 1080), endpoints)
        self.assertEqual(endpoints[('1.1.1.1', 1080)]['protocols'], {'socks4', 'socks5'})

    def test_skips_rows_with_missing_columns(self):
        endpoints = read_endpoints(self.path)
        self.assertNotIn(('9.9.9.9', 1080), endpoints)

    def test_skips_non_socks_rows(self):
        endpoints = read_endpoints(self.path)
        self.assertNotIn(('3.3.3.3', 8080), endpoints)

    def test_normalizes_country_to_uppercase(self):
        endpoints = read_endpoints(self.path)
        self.assertEqual(endpoints[('4.4.4.4', 9050)]['country'], 'US')
        self.assertEqual(endpoints[('4.4.4.4', 9050)]['city'], 'miami')

    def test_preserves_first_seen_order(self):
        endpoints = read_endpoints(self.path)
        self.assertEqual(list(endpoints.keys()),
                         [('1.1.1.1', 1080), ('2.2.2.2', 4145), ('4.4.4.4', 9050)])

    def test_records_single_protocol_for_normal_row(self):
        endpoints = read_endpoints(self.path)
        self.assertEqual(endpoints[('2.2.2.2', 4145)]['protocols'], {'socks4'})
        self.assertEqual(endpoints[('2.2.2.2', 4145)]['country'], 'DE')
        self.assertEqual(endpoints[('2.2.2.2', 4145)]['city'], 'Berlin')


if __name__ == '__main__':
    unittest.main()
