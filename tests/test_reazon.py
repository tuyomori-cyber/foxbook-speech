import asyncio
from pathlib import Path
import sys
import tempfile
import unittest

from service.reazon import ReazonManager


class ReazonLifetimeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        worker = root / "worker.py"
        worker.write_text('import json, sys\nprint(json.dumps({"event":"ready","initializationMs":1}), flush=True)\nfor line in sys.stdin:\n pass\n')
        for name in ("encoder-epoch-99-avg-1.int8.onnx", "decoder-epoch-99-avg-1.onnx", "joiner-epoch-99-avg-1.int8.onnx", "tokens.txt"):
            (root / name).touch()
        self.manager = ReazonManager(Path(sys.executable), worker, root, idle_seconds=0.05)

    async def asyncTearDown(self):
        await self.manager.stop()
        self.directory.cleanup()

    async def test_prepare_only_expires_and_recreates(self):
        self.assertEqual((await self.manager.prepare())[0], 1)
        await asyncio.sleep(0.12)
        self.assertIsNone(self.manager.process)
        self.assertEqual((await self.manager.prepare())[0], 2)

    async def test_owners_hold_worker_and_release_starts_new_timer(self):
        await self.manager.prepare()
        self.manager.acquire("one")
        self.manager.acquire("two")
        await asyncio.sleep(0.08)
        self.manager.release("one")
        await asyncio.sleep(0.08)
        self.assertIsNotNone(self.manager.process)
        self.manager.release("two")
        await asyncio.sleep(0.12)
        self.assertIsNone(self.manager.process)

    async def test_new_use_invalidates_old_timer(self):
        await self.manager.prepare()
        await asyncio.sleep(0.03)
        self.manager.acquire("recording")
        await self.manager.prepare()
        await asyncio.sleep(0.04)
        self.assertIsNotNone(self.manager.process)
        self.manager.release("recording")
        await asyncio.sleep(0.12)
        self.assertIsNone(self.manager.process)
