import asyncio
import csv
import time
import nbtlib
from nbtlib.tag import Compound, List
from main import build_proxy, build_root, parse_proxy_url

CSV_FILEPATH = "sorce/data.csv"
NBT_FILEPATH = "top_100_proxy.nbt"
TOP_N = 100
CONCURRENCY = 300
CONNECT_TIMEOUT = 2.5
HANDSHAKE_TIMEOUT = 2.0
PROGRESS_EVERY = 500

SOCKS5_VERSION = 0x05
SOCKS5_GREETING = b'\x05\x01\x00'
SOCKS5_NO_AUTH = 0x00
SOCKS4_REQUEST = b'\x04\x01\x00\x50\xc0\x00\x02\x01\x00'
SOCKS4_VERSION = 0x00
SOCKS4_GRANTED = 0x5A
SOCKS4_MAX_CODE = 0x5F

def read_endpoints(csv_filepath):
    endpoints = {}
    with open(csv_filepath, mode='r', encoding='utf-8', newline='') as csv_file:
        for row in csv.reader(csv_file):
            if not row or len(row) < 3:
                continue
            parsed = parse_proxy_url(row[0])
            if parsed is None:
                continue
            protocol, address, port = parsed
            key = (address, port)
            if key in endpoints:
                endpoints[key]['protocols'].add(protocol)
            else:
                endpoints[key] = {
                    'address': address,
                    'port': port,
                    'country': row[1].strip().upper(),
                    'city': row[2].strip(),
                    'protocols': {protocol}
                }
    return list(endpoints.values())

def parse_socks5_reply(data: bytes | None) -> int | None:
    if data is None or len(data) < 2 or data[0] != SOCKS5_VERSION:
        return None
    return data[1]

def parse_socks4_reply(data: bytes | None) -> int | None:
    if data is None or len(data) < 2 or data[0] != SOCKS4_VERSION:
        return None
    code = data[1]
    if SOCKS4_GRANTED <= code <= SOCKS4_MAX_CODE:
        return code
    return None

async def exchange(reader, writer, request: bytes, reply_size: int) -> bytes:
    writer.write(request)
    await writer.drain()
    return await asyncio.wait_for(reader.readexactly(reply_size), HANDSHAKE_TIMEOUT)

async def probe_protocol(protocol: str, address: str, port: int) -> float | None:
    start = time.perf_counter()
    writer = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(address, port), CONNECT_TIMEOUT
        )
        if protocol == 'socks5':
            reply = await exchange(reader, writer, SOCKS5_GREETING, 2)
            if parse_socks5_reply(reply) != SOCKS5_NO_AUTH:
                return None
        elif protocol == 'socks4':
            reply = await exchange(reader, writer, SOCKS4_REQUEST, 2)
            if parse_socks4_reply(reply) is None:
                return None
        return (time.perf_counter() - start) * 1000.0
    except Exception:
        return None
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

async def probe_entry(entry: dict) -> dict | None:
    protocols = [p for p in ('socks5', 'socks4') if p in entry['protocols']]
    for protocol in protocols:
        latency = await probe_protocol(protocol, entry['address'], entry['port'])
        if latency is not None:
            return {
                'address': entry['address'],
                'port': entry['port'],
                'country': entry['country'],
                'city': entry['city'],
                'protocol': protocol,
                'latency': latency
            }
    return None

def format_elapsed(seconds):
    minutes, remainder = divmod(int(seconds), 60)
    return f'{minutes:02d}:{remainder:02d}'

async def worker(queue: asyncio.Queue, results: list, counter: list, total: int, started_at: float):
    while True:
        entry = await queue.get()
        if entry is None:
            queue.task_done()
            break
        try:
            outcome = await probe_entry(entry)
            if outcome is not None:
                results.append(outcome)
        except Exception:
            pass
        finally:
            counter[0] += 1
            done = counter[0]
            if done % PROGRESS_EVERY == 0 or done == total:
                alive = len(results)
                best = min((e['latency'] for e in results), default=None)
                best_text = f'{best:.0f}ms' if best is not None else '-'
                elapsed = format_elapsed(time.perf_counter() - started_at)
                print(f'  [{done:>6}/{total}] alive={alive:>5} dead={done - alive:>6} best={best_text:>6} elapsed={elapsed}', flush=True)
            queue.task_done()

async def probe_all(entries, concurrency=CONCURRENCY):
    queue = asyncio.Queue()
    for entry in entries:
        queue.put_nowait(entry)

    results = []
    counter = [0]
    total = len(entries)
    started_at = time.perf_counter()

    workers = [
        asyncio.create_task(worker(queue, results, counter, total, started_at))
        for _ in range(concurrency)
    ]

    await queue.join()

    for _ in range(concurrency):
        queue.put_nowait(None)
    await asyncio.gather(*workers)

    return results

def rank_and_select(results, top_n=TOP_N):
    ordered = sorted(results, key=lambda entry: (
        entry['latency'], entry['country'], entry['city'],
        entry['address'], entry['port']
    ))
    return ordered[:top_n]

def save_proxies_nbt(selected, nbt_filepath):
    proxies_list = List[Compound]()
    for rank, entry in enumerate(selected, start=1):
        latency = round(entry['latency'])
        name = f"{entry['country']} {rank} {entry['city']} ({latency}ms)"
        proxies_list.append(
            build_proxy(name, entry['protocol'], entry['address'], entry['port'])
        )
    root = build_root(proxies_list)
    nbtlib.File(root, gzipped=False).save(nbt_filepath)

def main():
    entries = read_endpoints(CSV_FILEPATH)
    print(f'Testing {len(entries)} unique endpoints from {CSV_FILEPATH}', flush=True)

    results = asyncio.run(probe_all(entries))
    selected = rank_and_select(results)
    save_proxies_nbt(selected, NBT_FILEPATH)

    print(f'Working proxies: {len(results)}/{len(entries)}')
    print(f'Exported top {len(selected)} to {NBT_FILEPATH}')

if __name__ == '__main__':
    main()