import csv
import re
from collections import defaultdict

import nbtlib
from nbtlib.tag import Byte, Compound, Int, List, String

CSV_FILEPATH = "sorce/data.csv"
NBT_FILEPATH = "proxies.nbt"

PROXY_URL_PATTERN = re.compile(r'^(socks4|socks5)://([^:/]+):(\d+)$', re.IGNORECASE)


def parse_proxy_url(url):
    match = PROXY_URL_PATTERN.match(url.strip())
    if match is None:
        return None
    return match.group(1).lower(), match.group(2), int(match.group(3))


def build_setting(name, value):
    return Compound({'value': value, 'name': String(name)})


def build_proxy(display_name, protocol, address, port):
    settings = [
        build_setting('name', String(display_name)),
        build_setting('address', String(address)),
        build_setting('port', Int(port)),
        build_setting('enabled', Byte(0)),
    ]

    if protocol == 'socks4':
        settings.insert(1, build_setting('type', String('Socks4')))

    group = Compound({
        'sectionExpanded': Byte(1),
        'name': String('General'),
        'settings': List[Compound](settings)
    })

    return Compound({'settings': Compound({'groups': List[Compound]([group])})})


def read_proxies(csv_filepath):
    proxies_by_country = defaultdict(list)

    with open(csv_filepath, mode='r', encoding='utf-8', newline='') as csv_file:
        for row in csv.reader(csv_file):
            if not row or len(row) < 3:
                continue

            parsed = parse_proxy_url(row[0])
            if parsed is None:
                continue

            protocol, address, port = parsed
            proxies_by_country[row[1].strip().upper()].append(
                (protocol, address, port, row[2].strip())
            )

    return proxies_by_country


def convert_csv_to_proxies_nbt(csv_filepath, nbt_filepath):
    proxies_by_country = read_proxies(csv_filepath)

    proxies_list = List[Compound]()
    for country in sorted(proxies_by_country):
        country_proxies = proxies_by_country[country]
        for index, (protocol, address, port, city) in enumerate(country_proxies, start=1):
            display_name = f'{country} {index} {city}'
            proxies_list.append(build_proxy(display_name, protocol, address, port))

    root = Compound({'proxies': proxies_list, 'settings': Compound({})})

    nbt_file = nbtlib.File(root, gzipped=False)
    nbt_file.save(nbt_filepath)
    print(f'Proxies {len(proxies_list)} saved to {nbt_filepath}')


if __name__ == "__main__":
    convert_csv_to_proxies_nbt(CSV_FILEPATH, NBT_FILEPATH)
