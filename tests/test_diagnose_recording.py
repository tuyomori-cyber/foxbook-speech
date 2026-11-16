from __future__ import annotations

import argparse
from pathlib import Path
import unittest

from scripts.diagnose_recording import connect, seconds


class FakeSocket:
    def __init__(self, error: OSError | None) -> None:
        self.error = error
        self.closed = False

    def settimeout(self, _seconds: int) -> None:
        pass

    def connect(self, _path: str) -> None:
        if self.error:
            raise self.error

    def close(self) -> None:
        self.closed = True


class FakeSocketFactory:
    def __init__(self, errors: list[OSError | None]) -> None:
        self.errors = errors
        self.sockets: list[FakeSocket] = []

    def __call__(self, _family: int, _kind: int) -> FakeSocket:
        result = FakeSocket(self.errors[len(self.sockets)])
        self.sockets.append(result)
        return result


class DiagnoseRecordingTest(unittest.TestCase):
    def test_accepts_duration_within_recording_limit(self) -> None:
        self.assertEqual(seconds("1"), 1)
        self.assertEqual(seconds("30"), 30)

    def test_rejects_invalid_duration(self) -> None:
        for value in ("0", "31", "five"):
            with self.assertRaises(argparse.ArgumentTypeError):
                seconds(value)

    def test_connect_retries_a_socket_that_is_not_ready_yet(self) -> None:
        factory = FakeSocketFactory([FileNotFoundError(), ConnectionRefusedError(), None])
        clock = iter((0, 0, 0, 0))
        connection = connect(Path("/run/user/1000/foxbook-speech.sock"), factory,
                             sleep=lambda _seconds: None, monotonic=lambda: next(clock))
        self.assertIs(connection, factory.sockets[-1])
        self.assertTrue(factory.sockets[0].closed)
        self.assertTrue(factory.sockets[1].closed)


if __name__ == "__main__":
    unittest.main()
