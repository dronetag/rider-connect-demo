import argparse
import asyncio
import binascii
import json
import pathlib
import betterproto
import serial_asyncio
from datetime import datetime
from typing import Callable, Dict, IO, List, Awaitable, Optional, Tuple
from dtproto_receiver import dri_message_pb2, DriMessage


class Slip:
    END = 0x0A
    ESC = 0xDB
    ESC_END = 0xDC
    ESC_ESC = 0xDD

    END_b = b"\n"
    ESC_b = b"\xdb"
    ESC_END_b = b"\xdc"
    ESC_ESC_b = b"\xdd"

    @staticmethod
    def encode(data: bytes) -> bytes:
        return (
            data.replace(Slip.ESC_b, Slip.ESC_b + Slip.ESC_ESC_b)
                .replace(Slip.END_b, Slip.ESC_b + Slip.ESC_END_b)
            + Slip.END_b
        )

    @staticmethod
    def decode(data: bytes) -> bytes:
        return (
            data.replace(Slip.ESC_b + Slip.ESC_ESC_b, Slip.ESC_b)
                .replace(Slip.ESC_b + Slip.ESC_END_b, Slip.END_b)
        ).strip(Slip.END_b)


HandlerType = Callable[[bytes], Awaitable[None]]


class SlipSerialReader(asyncio.Protocol):
    def __init__(self, handler_map: Dict[int, List[HandlerType]]) -> None:
        self.buffer = bytearray()
        self.transport: Optional[asyncio.Transport] = None
        self.handler_map = handler_map

    def connection_made(self, transport: asyncio.Transport) -> None:
        self.transport = transport
        port = transport.get_extra_info('serial')
        print(f"Connected to {port.port}")

    def data_received(self, data: bytes) -> None:
        self.buffer.extend(data)
        while Slip.END in self.buffer:
            end_index = self.buffer.index(Slip.END)
            raw_packet = bytes(self.buffer[:end_index + 1])
            self.buffer = self.buffer[end_index + 1:]
            asyncio.create_task(self.process_packet(raw_packet))

    async def process_packet(self, packet: bytes) -> None:
        try:
            decoded = Slip.decode(packet)
            if not decoded:
                return
            address = decoded[0]
            payload = decoded[1:]
            handlers = self.handler_map.get(address, [])
            if handlers:
                await asyncio.gather(*(handler(payload) for handler in handlers))
            else:
                print(f"No handlers registered for address {address}")
        except Exception as e:
            print(f"Error processing packet: {e}")


class SlipDispatcher:
    def __init__(self) -> None:
        self.handler_map: Dict[int, List[HandlerType]] = {}

    def register_handler(self, address: int, handler: HandlerType) -> None:
        if address not in self.handler_map:
            self.handler_map[address] = []
        self.handler_map[address].append(handler)

    async def start(self, port: str, baudrate: int = 115200) -> Tuple[serial_asyncio.SerialTransport, SlipSerialReader]:
        loop = asyncio.get_running_loop()
        transport, protocol = await serial_asyncio.create_serial_connection(
            loop,
            lambda: SlipSerialReader(self.handler_map),
            port,
            baudrate
        )
        return transport, protocol


class ProtobufDelimitedBuffer:
    def __init__(self, consumer: Callable[[bytes], Awaitable[None]]):
        self.buffer = bytearray()
        self.consumer = consumer

    async def feed(self, data: bytes):
        self.buffer.extend(data)
        while True:
            msg, remaining = self._extract_next_message(self.buffer)
            if msg is None:
                break
            self.buffer = remaining
            await self.consumer(msg)

    def _read_varint(self, buf: bytearray) -> Tuple[int, int]:
        result = 0
        shift = 0
        for i, byte in enumerate(buf):
            result |= (byte & 0x7F) << shift
            if not (byte & 0x80):
                return result, i + 1
            shift += 7
        raise ValueError("Incomplete varint")

    def _extract_next_message(self, buf: bytearray) -> Tuple[Optional[bytes], bytearray]:
        try:
            size, size_len = self._read_varint(buf)
            if len(buf) < size_len + size:
                return None, buf
            msg = bytes(buf[size_len:size_len + size])
            return msg, buf[size_len + size:]
        except Exception:
            return None, buf


try:
    from dt_odid_parser import dt_odid_parser as _dt_odid_parser
    _has_internal_parser = True
except Exception as e:
    print(f"Dronetag internal parser not available: {e}")
    _has_internal_parser = False


def _open_storage(storage_arg: str, port: str) -> IO[str]:
    directory = pathlib.Path(storage_arg)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    devname = pathlib.Path(port).name
    return open(directory / f"{timestamp}_{devname}.jsonl", "a")


def _write_jsonl(f: IO[str], data: dict) -> None:
    f.write(json.dumps(data, default=str) + "\n")
    f.flush()


async def main():
    parser = argparse.ArgumentParser(description="Async SLIP Serial Reader with Handler Dispatch")
    parser.add_argument(
        "-p", "--port", required=True, help="Serial port to open (e.g., /dev/ttyUSB0 or COM3)"
    )
    parser.add_argument(
        "-b", "--baudrate", type=int, default=115200, help="Baudrate for the serial port (default: 115200)"
    )
    parser.add_argument(
        "--init", type=str, default="2A0A0A", help="Initial message to send as hex string (e.g., '010203aabb')"
    )
    parser.add_argument(
        "--storage", type=str, default=None,
        help="Directory (or .jsonl file path) to write decoded messages as JSONL. "
             "When a directory is given a timestamped file is created per session."
    )

    args = parser.parse_args()

    storage_file: Optional[IO[str]] = None
    if args.storage:
        storage_file = _open_storage(args.storage, args.port)
        print(f"Storing decoded messages to: {storage_file.name}")

    if _has_internal_parser:
        async def dt_dri_pb_handler(payload: bytes) -> None:
            print(f"Handled PB message with payload: {binascii.hexlify(payload)}")
            dri_message = dri_message_pb2.DriMessage.FromString(payload)
            if not dri_message.HasField("odid_payload"):
                return
            ser_dict = _dt_odid_parser(dri_message)
            if not ser_dict:
                print("Message could not be parsed")
                return
            print(json.dumps(ser_dict, default=str))
            if storage_file:
                _write_jsonl(storage_file, ser_dict)
    else:
        async def dt_dri_pb_handler(payload: bytes) -> None:
            print(f"Handled PB message with payload: {binascii.hexlify(payload)}")
            try:
                dri = DriMessage().parse(payload)
                dri_dict = dri.to_dict(casing=betterproto.Casing.SNAKE)
                print(json.dumps(dri_dict))
                if storage_file:
                    _write_jsonl(storage_file, dri_dict)
            except ValueError as e:
                print(f"Could not parse dri message: {e}")

    protobuf_buffer = ProtobufDelimitedBuffer(dt_dri_pb_handler)

    async def dt_odid_pb_handler(payload: bytes) -> None:
        await protobuf_buffer.feed(payload)

    dispatcher = SlipDispatcher()
    dispatcher.register_handler(0x2A, dt_odid_pb_handler)

    transport, _ = await dispatcher.start(args.port, baudrate=args.baudrate)

    if args.init:
        try:
            message = binascii.unhexlify(args.init)
            encoded = Slip.encode(message)
            transport.write(encoded)
            print(f"Sent initial hex message: {message.hex()}")
        except binascii.Error as e:
            print(f"Invalid hex string in --init: {e}")

    try:
        await asyncio.Event().wait()
    finally:
        if storage_file:
            storage_file.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopped.")
