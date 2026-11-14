"""Volcengine V3 TTS binary WebSocket protocol.

Implements the frame format used by
wss://openspeech.bytedance.com/api/v3/tts/bidirection
"""

from __future__ import annotations

import json
import struct
from enum import IntEnum


class MessageType(IntEnum):
    FULL_CLIENT_REQUEST = 0b0001
    AUDIO_ONLY_CLIENT = 0b0010
    FULL_SERVER_RESPONSE = 0b1001
    AUDIO_ONLY_SERVER = 0b1011
    ERROR = 0b1111


class EventSend(IntEnum):
    StartConnection = 1
    FinishConnection = 2
    StartSession = 100
    CancelSession = 101
    FinishSession = 102
    TaskRequest = 200


class EventReceive(IntEnum):
    ConnectionStarted = 50
    ConnectionFailed = 51
    ConnectionFinished = 52
    SessionStarted = 150
    SessionCanceled = 151
    SessionFinished = 152
    SessionFailed = 153
    UsageResponse = 154
    TTSSentenceStart = 350
    TTSSentenceEnd = 351
    TTSResponse = 352
    TTSEnded = 359


MSG_FLAG_WITH_EVENT = 0b0100


def build_frame(
    event: EventSend,
    payload: dict | None = None,
    session_id: str | None = None,
    message_type: MessageType = MessageType.FULL_CLIENT_REQUEST,
) -> bytes:
    """Build a V3 binary WebSocket frame."""
    header = bytes(
        [
            (0x1 << 4) | 0x1,  # version 1, header size 4
            (message_type << 4) | MSG_FLAG_WITH_EVENT,
            (0x1 << 4) | 0x0,  # JSON, no compression
            0x00,
        ]
    )
    body = bytearray(header)
    body.extend(struct.pack(">I", int(event)))

    if session_id and event not in (EventSend.StartConnection, EventSend.FinishConnection):
        sid = session_id.encode("utf-8")
        body.extend(struct.pack(">I", len(sid)))
        body.extend(sid)

    payload_bytes = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    body.extend(struct.pack(">I", len(payload_bytes)))
    body.extend(payload_bytes)
    return bytes(body)


def parse_frame(data: bytes) -> tuple[int, str, bytes, int]:
    """Parse a server frame -> (event, session_id, payload, sequence)."""
    if len(data) < 8:
        raise ValueError("Frame too short")

    msg_type = (data[1] >> 4) & 0x0F
    flags = data[1] & 0x0F
    offset = 4
    event = 0
    session_id = ""
    sequence = 0

    if flags & MSG_FLAG_WITH_EVENT:
        event = struct.unpack(">I", data[offset : offset + 4])[0]
        offset += 4

        if event not in (
            EventReceive.ConnectionStarted,
            EventReceive.ConnectionFailed,
            EventReceive.ConnectionFinished,
        ):
            sid_len = struct.unpack(">I", data[offset : offset + 4])[0]
            offset += 4
            session_id = data[offset : offset + sid_len].decode("utf-8")
            offset += sid_len

    if flags & 0b1 or flags & 0b11:
        sequence = struct.unpack(">i", data[offset : offset + 4])[0]
        offset += 4

    if msg_type == MessageType.ERROR and offset + 4 <= len(data):
        offset += 4  # error code

    if offset + 4 > len(data):
        return event, session_id, b"", sequence

    payload_len = struct.unpack(">I", data[offset : offset + 4])[0]
    offset += 4
    payload = data[offset : offset + payload_len]
    return event, session_id, payload, sequence
