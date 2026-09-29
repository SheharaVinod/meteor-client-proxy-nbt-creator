import asyncio
import gc
import socket
import time
import unittest
import warnings
from unittest import mock

import top_100_proxy
from top_100_proxy import probe, probe_protocol


async def start_server(handler):
    server = await asyncio.start_server(handler, '127.0.0.1', 0)
    return server, server.sockets[0].getsockname()[1]


async def close_writer(writer):
    writer.close()
    await writer.wait_closed()


async def socks5_handler(reader, writer):
    await reader.readexactly(3)
    writer.write(b'\x05\x00')
    await writer.drain()
    await close_writer(writer)


async def socks5_auth_handler(reader, writer):
    await reader.readexactly(3)
    writer.write(b'\x05\xff')
    await writer.drain()
    await close_writer(writer)


async def socks4_handler(reader, writer):
    try:
        await reader.readexactly(9)
    except asyncio.IncompleteReadError:
        await close_writer(writer)
        return
    writer.write(b'\x00\x5b')
    await writer.drain()
    await close_writer(writer)


async def wrong_protocol_handler(reader, writer):
    await reader.readexactly(3)
    writer.write(b'HTTP/1.1 400 Bad Request\r\n\r\n')
    await writer.drain()
    await close_writer(writer)


async def silent_handler(reader, writer):
    await reader.readexactly(3)
    while await reader.read(1024):
        pass
    await close_writer(writer)


async def delayed_socks5_handler(reader, writer):
    try:
        await reader.readexactly(3)
    except asyncio.IncompleteReadError:
        await close_writer(writer)
        return
    await asyncio.sleep(0.05)
    writer.write(b'\x05\x00')
    await writer.drain()
    await close_writer(writer)


async def dual_handler(reader, writer):
    try:
        head = await reader.readexactly(1)
        if head == b'\x05':
            await reader.readexactly(2)
            writer.write(b'\x05\x00')
        else:
            await reader.readexactly(8)
            writer.write(b'\x00\x5a')
        await writer.drain()
    except asyncio.IncompleteReadError:
        await close_writer(writer)
        return
    await close_writer(writer)


def closed_port():
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def run(coroutine):
    return asyncio.run(coroutine)


class ProbeProtocolTest(unittest.TestCase):
    def test_live_socks5_returns_latency(self):
        async def scenario():
            server, port = await start_server(socks5_handler)
            try:
                return await probe_protocol('socks5', '127.0.0.1', port)
            finally:
                server.close()
                await server.wait_closed()

        latency = run(scenario())
        self.assertIsNotNone(latency)
        self.assertGreaterEqual(latency, 0.0)
        self.assertLess(latency, 2000.0)

    def test_live_socks4_returns_latency(self):
        async def scenario():
            server, port = await start_server(socks4_handler)
            try:
                return await probe_protocol('socks4', '127.0.0.1', port)
            finally:
                server.close()
                await server.wait_closed()

        self.assertIsNotNone(run(scenario()))

    def test_auth_required_socks5_is_rejected(self):
        async def scenario():
            server, port = await start_server(socks5_auth_handler)
            try:
                return await probe_protocol('socks5', '127.0.0.1', port)
            finally:
                server.close()
                await server.wait_closed()

        self.assertIsNone(run(scenario()))

    def test_refused_connection_is_dead(self):
        self.assertIsNone(run(probe_protocol('socks5', '127.0.0.1', closed_port())))

    def test_wrong_protocol_reply_is_dead(self):
        async def scenario():
            server, port = await start_server(wrong_protocol_handler)
            try:
                return await probe_protocol('socks5', '127.0.0.1', port)
            finally:
                server.close()
                await server.wait_closed()

        self.assertIsNone(run(scenario()))

    def test_silent_server_times_out(self):
        async def scenario():
            server, port = await start_server(silent_handler)
            try:
                return await asyncio.wait_for(
                    probe_protocol('socks5', '127.0.0.1', port), 10)
            finally:
                server.close()
                await server.wait_closed()

        self.assertIsNone(run(scenario()))

    def test_latency_is_in_milliseconds(self):
        async def scenario():
            server, port = await start_server(delayed_socks5_handler)
            try:
                return await probe_protocol('socks5', '127.0.0.1', port)
            finally:
                server.close()
                await server.wait_closed()

        latency = run(scenario())
        self.assertIsNotNone(latency)
        self.assertGreaterEqual(latency, 40.0)
        self.assertLess(latency, 5000.0)

    def test_writer_is_closed_after_probe(self):
        async def scenario():
            server, port = await start_server(socks5_handler)
            try:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter('always')
                    latency = await probe_protocol('socks5', '127.0.0.1', port)
                    gc.collect()
                return latency, caught
            finally:
                server.close()
                await server.wait_closed()

        latency, caught = run(scenario())
        self.assertIsNotNone(latency)
        leaks = [w for w in caught
                 if issubclass(w.category, ResourceWarning)
                 and 'StreamWriter' in str(w.message)]
        self.assertEqual(leaks, [])

    def test_writer_socket_is_closed_before_probe_returns(self):
        captured = []
        real_open_connection = asyncio.open_connection

        async def capturing_open_connection(*args, **kwargs):
            reader, writer = await real_open_connection(*args, **kwargs)
            captured.append(writer)
            return reader, writer

        async def scenario():
            server, port = await start_server(socks5_handler)
            try:
                with mock.patch.object(asyncio, 'open_connection',
                                       capturing_open_connection):
                    latency = await probe_protocol('socks5', '127.0.0.1', port)
                    fileno = captured[0].get_extra_info('socket').fileno()
                return latency, fileno
            finally:
                server.close()
                await server.wait_closed()

        latency, fileno = run(scenario())
        self.assertIsNotNone(latency)
        self.assertEqual(len(captured), 1)
        self.assertEqual(fileno, -1)

    def test_connect_timeout_governs_a_slow_connect(self):
        real_open_connection = asyncio.open_connection

        async def slow_open_connection(*args, **kwargs):
            await asyncio.sleep(0.8)
            return await real_open_connection(*args, **kwargs)

        async def scenario():
            server, port = await start_server(socks5_handler)
            try:
                with mock.patch.object(top_100_proxy, 'HANDSHAKE_TIMEOUT', 0.4), \
                        mock.patch.object(asyncio, 'open_connection',
                                          slow_open_connection):
                    return await probe_protocol('socks5', '127.0.0.1', port)
            finally:
                server.close()
                await server.wait_closed()

        self.assertIsNotNone(run(scenario()))

    def test_handshake_timeout_governs_an_unanswered_server(self):
        async def scenario():
            server, port = await start_server(silent_handler)
            try:
                with mock.patch.object(top_100_proxy, 'HANDSHAKE_TIMEOUT', 0.4):
                    start = time.perf_counter()
                    result = await probe_protocol('socks5', '127.0.0.1', port)
                    return result, time.perf_counter() - start
            finally:
                server.close()
                await server.wait_closed()

        result, elapsed = run(scenario())
        self.assertIsNone(result)
        self.assertLess(elapsed, 2.0)

    def test_wrong_protocol_socks4_reply_is_dead(self):
        async def scenario():
            server, port = await start_server(wrong_protocol_handler)
            try:
                return await probe_protocol('socks4', '127.0.0.1', port)
            finally:
                server.close()
                await server.wait_closed()

        self.assertIsNone(run(scenario()))

    def test_connect_timeout_governs_unreachable_port(self):
        async def scenario():
            return await asyncio.wait_for(
                probe_protocol('socks5', '127.0.0.1', closed_port()), 1.5)

        self.assertIsNone(run(scenario()))


class ProbeTest(unittest.TestCase):
    def test_probe_returns_result_for_live_socks5(self):
        async def scenario():
            server, port = await start_server(socks5_handler)
            try:
                entry = {'address': '127.0.0.1', 'port': port, 'country': 'US',
                         'city': 'Ashburn', 'protocols': {'socks5'}}
                return await probe(entry, asyncio.Semaphore(10)), port
            finally:
                server.close()
                await server.wait_closed()

        result, port = run(scenario())
        self.assertIsNotNone(result)
        self.assertEqual(result['protocol'], 'socks5')
        self.assertEqual(result['address'], '127.0.0.1')
        self.assertEqual(result['port'], port)
        self.assertEqual(result['country'], 'US')
        self.assertEqual(result['city'], 'Ashburn')
        self.assertGreaterEqual(result['latency'], 0.0)
        self.assertEqual(set(result),
                         {'address', 'port', 'country', 'city', 'protocol', 'latency'})

    def test_probe_falls_back_to_socks4_on_socks4_only_server(self):
        async def scenario():
            server, port = await start_server(socks4_handler)
            try:
                entry = {'address': '127.0.0.1', 'port': port, 'country': 'TH',
                         'city': 'Sing Buri', 'protocols': {'socks4', 'socks5'}}
                return await probe(entry, asyncio.Semaphore(10))
            finally:
                server.close()
                await server.wait_closed()

        result = run(scenario())
        self.assertIsNotNone(result)
        self.assertEqual(result['protocol'], 'socks4')
        self.assertEqual(result['country'], 'TH')

    def test_probe_prefers_socks5_when_both_are_served(self):
        async def scenario():
            server, port = await start_server(dual_handler)
            try:
                entry = {'address': '127.0.0.1', 'port': port, 'country': 'DE',
                         'city': 'Frankfurt', 'protocols': {'socks4', 'socks5'}}
                return await probe(entry, asyncio.Semaphore(1))
            finally:
                server.close()
                await server.wait_closed()

        result = run(scenario())
        self.assertIsNotNone(result)
        self.assertEqual(result['protocol'], 'socks5')

    def test_probe_returns_none_when_nothing_answers(self):
        entry = {'address': '127.0.0.1', 'port': closed_port(), 'country': 'US',
                 'city': 'Unknown', 'protocols': {'socks5'}}
        self.assertIsNone(run(probe(entry, asyncio.Semaphore(10))))


if __name__ == '__main__':
    unittest.main()
