import csv
import re
from collections import defaultdict
import nbtlib
from nbtlib.tag import Compound, List, String, Int, Byte


def parse_proxy_url(url):
    match = re.match(r'^(socks[45])://([^:/]+):(\d+)$', url.strip(), re.IGNORECASE)
    if match:
        protocol = match.group(1).lower()
        address = match.group(2)
        port = int(match.group(3))
        return protocol, address, port
    return None


def convert_csv_to_proxies_nbt(csv_filepath, nbt_filepath):
    proxies_by_country = defaultdict(list)

    with open(csv_filepath, mode='r', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or len(row) < 3:
                continue

            raw_url = row[0].strip()
            country = row[1].strip().upper()
            city_name = row[2].strip()

            parsed = parse_proxy_url(raw_url)
            if not parsed:
                continue

            protocol, address, port = parsed
            proxies_by_country[country].append({
                'address': address,
                'port': port,
                'city': city_name
            })

    sorted_countries = sorted(proxies_by_country.keys())
    proxies_list = List[Compound]()

    for country in sorted_countries:
        country_proxies = proxies_by_country[country]
        for index, proxy in enumerate(country_proxies, start=1):
            proxy_display_name = f"{country} {index} {proxy['city']}"

            general_settings = List[Compound]([
                Compound({'name': String('name'), 'value': String(proxy_display_name)}),
                Compound({'name': String('address'), 'value': String(proxy['address'])}),
                Compound({'name': String('port'), 'value': Int(proxy['port'])}),
                Compound({'name': String('enabled'), 'value': Byte(0)})
            ])

            groups_list = List[Compound]([
                Compound({
                    'sectionExpanded': Byte(1),
                    'name': String('General'),
                    'settings': general_settings
                })
            ])

            proxy_compound = Compound({
                'settings': Compound({
                    'groups': groups_list
                })
            })

            proxies_list.append(proxy_compound)

    root = Compound({
        'proxies': proxies_list,
        'settings': Compound({})
    })

    nbt_file = nbtlib.File(root, gzipped=True)
    nbt_file.save(nbt_filepath)
    print(f"Proxies {len(proxies_list)} saved to {nbt_filepath}")


if __name__ == "__main__":
    input_csv = "sorce/data.csv"
    output_nbt = "proxies.nbt"

    convert_csv_to_proxies_nbt(input_csv, output_nbt)
