from __future__ import annotations

import io
import json
import struct
import unittest

from native_host.foxbook_speech import MAX_MESSAGE_BYTES, read_native, service_socket_path, write_native


class NativeHostFramingTest(unittest.TestCase):
    def test_round_trip(self) -> None:
        output = io.BytesIO()
        write_native(output, {"version": 1, "action": "get_status"})
        self.assertEqual(read_native(io.BytesIO(output.getvalue())), {"version": 1, "action": "get_status"})

    def test_rejects_oversized_and_non_object_messages(self) -> None:
        with self.assertRaises(ValueError):
            read_native(io.BytesIO(struct.pack("=I", MAX_MESSAGE_BYTES + 1)))
        payload = json.dumps(["not", "an", "object"]).encode()
        with self.assertRaises(ValueError):
            read_native(io.BytesIO(struct.pack("=I", len(payload)) + payload))

    def test_socket_path_can_be_configured_for_service_deployment(self) -> None:
        import os
        previous = os.environ.get("FOXBOOK_SPEECH_SOCKET")
        try:
            os.environ["FOXBOOK_SPEECH_SOCKET"] = "/run/user/1000/foxbook-speech/test.sock"
            self.assertEqual(str(service_socket_path()), "/run/user/1000/foxbook-speech/test.sock")
        finally:
            if previous is None:
                os.environ.pop("FOXBOOK_SPEECH_SOCKET", None)
            else:
                os.environ["FOXBOOK_SPEECH_SOCKET"] = previous
