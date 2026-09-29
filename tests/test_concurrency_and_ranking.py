import asyncio
import io
import re
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

import top_100_proxy
from top_100_proxy import (
    CONCURRENCY,
    PROGRESS_EVERY,
    format_elapsed,
    probe,
    probe_all,
    probe_protocol,
    rank_and_select,
    report_progress,
)

ACQUIRE_TIMEOUT = 0.5


def result(latency, country='US', city='Ashburn', address='1.1.1.1', port=1080,
           protocol='socks5'):
    return {
        'address': address,
        'port': port,
        'country': country,
        'city': city,
        'protocol': protocol,
        'latency': latency,
    }


def progress_fields(line):
    fields = {}
    for key in ('alive', 'dead', 'best'):
        match = re.search(rf'\b{key}=\s*(\S+)', line)
        fields[key] = match.group(1) if match is not None else None
    return fields


def run_probe_all(endpoints, concurrency, probe_impl):
    original = top_100_proxy.probe
    top_100_proxy.probe = probe_impl
    try:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            results = asyncio.run(probe_all(endpoints, concurrency=concurrency))
    finally:
        top_100_proxy.probe = original
    return results, buffer.getvalue()


class RankAndSelectTest(unittest.TestCase):
    def assert_orders_deterministically(self, first, second, field):
        expected = [first[field], second[field]]
        forward = [entry[field] for entry in rank_and_select([first, second])]
        backward = [entry[field] for entry in rank_and_select([second, first])]
        self.assertEqual(forward, expected)
        self.assertEqual(backward, expected)

    def test_sorts_by_latency_ascending(self):
        selected = rank_and_select([result(90.0), result(10.0), result(50.0)])
        self.assertEqual([entry['latency'] for entry in selected],
                         [10.0, 50.0, 90.0])

    def test_truncates_to_top_n(self):
        selected = rank_and_select([result(float(n)) for n in range(500)], top_n=100)
        self.assertEqual(len(selected), 100)
        self.assertEqual(selected[0]['latency'], 0.0)
        self.assertEqual(selected[-1]['latency'], 99.0)

    def test_ties_break_deterministically(self):
        first = rank_and_select([result(10.0, country='US'),
                                 result(10.0, country='CA')])
        second = rank_and_select([result(10.0, country='CA'),
                                  result(10.0, country='US')])
        self.assertEqual([entry['country'] for entry in first], ['CA', 'US'])
        self.assertEqual([entry['country'] for entry in first],
                         [entry['country'] for entry in second])

    def test_ties_break_on_city(self):
        self.assert_orders_deterministically(
            result(10.0, city='Amsterdam'), result(10.0, city='Zurich'), 'city')

    def test_ties_break_on_address(self):
        self.assert_orders_deterministically(
            result(10.0, address='1.1.1.1'), result(10.0, address='2.2.2.2'),
            'address')

    def test_ties_break_on_port(self):
        self.assert_orders_deterministically(
            result(10.0, port=1080), result(10.0, port=1081), 'port')

    def test_latency_is_not_rounded(self):
        self.assert_orders_deterministically(
            result(10.4), result(10.49), 'latency')

    def test_handles_fewer_results_than_top_n(self):
        self.assertEqual(len(rank_and_select([result(5.0)], top_n=100)), 1)

    def test_empty_input(self):
        self.assertEqual(rank_and_select([]), [])


class FormatElapsedTest(unittest.TestCase):
    def test_formats_minutes_and_seconds(self):
        self.assertEqual(format_elapsed(0), '00:00')
        self.assertEqual(format_elapsed(9), '00:09')
        self.assertEqual(format_elapsed(65), '01:05')
        self.assertEqual(format_elapsed(3725), '62:05')

    def test_truncates_rather_than_rounds_fractional_seconds(self):
        self.assertEqual(format_elapsed(65.9), '01:05')
        self.assertEqual(format_elapsed(0.99), '00:00')
        self.assertEqual(format_elapsed(119.5), '01:59')


class ConcurrencyConfigTest(unittest.TestCase):
    def test_concurrency_within_required_range(self):
        self.assertGreaterEqual(CONCURRENCY, 200)
        self.assertLessEqual(CONCURRENCY, 500)

    def test_progress_every_is_pinned(self):
        self.assertEqual(PROGRESS_EVERY, 500)


class ReportProgressTest(unittest.TestCase):
    def test_line_reports_alive_dead_and_best(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            report_progress(10, 12, [result(12.0), result(30.5), result(7.25)],
                            time.perf_counter())

        line = buffer.getvalue().strip()
        fields = progress_fields(line)
        self.assertIn('10/12', line)
        self.assertEqual(fields['alive'], '3')
        self.assertEqual(fields['dead'], '7')
        self.assertEqual(fields['best'], '7ms')

    def test_line_layout_is_pinned(self):
        buffer = io.StringIO()
        with mock.patch.object(top_100_proxy.time, 'perf_counter',
                               return_value=100.0):
            with redirect_stdout(buffer):
                report_progress(1000, 1000, [result(12.0)], 100.0)

        self.assertEqual(
            buffer.getvalue(),
            '  [  1000/1000] alive=     1 dead=  999 best= 12ms  elapsed=00:00\n')

    def test_no_results_renders_placeholder_instead_of_raising(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            report_progress(5, 5, [], time.perf_counter())

        fields = progress_fields(buffer.getvalue().strip())
        self.assertEqual(fields['alive'], '0')
        self.assertEqual(fields['dead'], '5')
        self.assertEqual(fields['best'], '-')


class ProbeProtocolErrorTest(unittest.TestCase):
    def test_out_of_range_port_is_dead(self):
        async def scenario():
            return await asyncio.wait_for(
                probe_protocol('socks5', '127.0.0.1', 99999), 5)

        self.assertIsNone(asyncio.run(scenario()))

    def test_unencodable_host_is_dead(self):
        async def failing_open_connection(*args, **kwargs):
            raise UnicodeEncodeError('idna', 'a' * 64, 0, 1, 'label too long')

        async def scenario():
            with mock.patch.object(asyncio, 'open_connection',
                                   failing_open_connection):
                return await probe_protocol('socks5', 'a' * 64, 1080)

        self.assertIsNone(asyncio.run(scenario()))


class ProbeSemaphoreTest(unittest.TestCase):
    def test_probe_blocks_on_a_held_permit(self):
        entry = {'address': '127.0.0.1', 'port': 1, 'country': 'US',
                 'city': 'Ashburn', 'protocols': set()}

        async def scenario():
            control = asyncio.create_task(probe(entry, asyncio.Semaphore(1)))
            self.assertIsNone(await asyncio.wait_for(control, 1))

            semaphore = asyncio.Semaphore(1)
            await semaphore.acquire()
            task = asyncio.create_task(probe(entry, semaphore))
            await asyncio.wait_for(asyncio.sleep(0.01), 1)
            self.assertFalse(task.done())
            semaphore.release()
            self.assertIsNone(await asyncio.wait_for(task, 1))

        asyncio.run(scenario())


class ProbeAllTest(unittest.TestCase):
    def setUp(self):
        self.live = {'address': '127.0.0.1', 'port': 1, 'country': 'US',
                     'city': 'Ashburn', 'protocols': {'socks5'}}

    def endpoints(self, *ports):
        return {('127.0.0.1', port): dict(self.live, port=port) for port in ports}

    def test_returns_only_successful_results(self):
        live = self.live

        async def fake_probe(entry, semaphore):
            return result(12.0) if entry is live else None

        endpoints = {
            ('127.0.0.1', 1): live,
            ('127.0.0.1', 2): dict(live, port=2),
            ('127.0.0.1', 3): dict(live, port=3),
        }
        results, output = run_probe_all(endpoints, 2, fake_probe)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['latency'], 12.0)
        self.assertIn('3/3', output)

    def test_one_failing_probe_does_not_lose_the_others(self):
        async def flaky_probe(entry, semaphore):
            if entry['port'] == 2:
                raise ValueError('connect(): port must be 0-65535')
            if entry['port'] == 3:
                return None
            return result(12.0)

        results, output = run_probe_all(self.endpoints(1, 2, 3), 2, flaky_probe)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['latency'], 12.0)
        self.assertIn('3/3', output)

    def test_cancellation_still_stops_the_run(self):
        async def cancelling_probe(entry, semaphore):
            raise asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            run_probe_all(self.endpoints(1, 2, 3), 2, cancelling_probe)

    def test_all_dead_run_never_builds_a_best_of_nothing(self):
        async def dead_probe(entry, semaphore):
            return None

        total = PROGRESS_EVERY + 1
        results, output = run_probe_all(self.endpoints(*range(total)), 10,
                                        dead_probe)

        self.assertEqual(results, [])
        lines = [line for line in output.splitlines() if line.strip()]
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertEqual(progress_fields(line)['best'], '-')
        last = progress_fields(lines[-1])
        self.assertEqual(last['alive'], '0')
        self.assertEqual(last['dead'], str(total))
        self.assertNotIn('ms', last['best'])

    def test_rejects_non_positive_concurrency(self):
        for concurrency in (0, -1):
            with self.subTest(concurrency=concurrency):
                with redirect_stdout(io.StringIO()):
                    with self.assertRaises(ValueError) as caught:
                        asyncio.run(asyncio.wait_for(
                            probe_all(self.endpoints(1, 2), concurrency), 1))
                self.assertIn('concurrency', str(caught.exception))

    def test_never_exceeds_semaphore_limit(self):
        state = {'current': 0, 'peak': 0}

        async def counting_probe(entry, semaphore):
            await asyncio.wait_for(semaphore.acquire(), ACQUIRE_TIMEOUT)
            try:
                state['current'] += 1
                state['peak'] = max(state['peak'], state['current'])
                await asyncio.sleep(0)
                state['current'] -= 1
            finally:
                semaphore.release()
            return result(1.0)

        run_probe_all(self.endpoints(*range(50)), 5, counting_probe)

        self.assertEqual(state['peak'], 5)
        self.assertEqual(state['current'], 0)


if __name__ == '__main__':
    unittest.main()
