#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RPi5 <-> Pixhawk Pro bridge (Binary V2 UART only)
- gRPC: KrakenGrpc.getDoaResult(stream), KrakenGrpc.setDaqFrequency(SetDAQFrequency)
- UART: 0xAA 0xAB | msg_id | len | payload | checksum
Env:
  KRAKEN_HOST=127.0.0.1
  KRAKEN_PORT=5005
  PIXHAWK_UART=/dev/serial0
  PIXHAWK_BAUD=921600
  DF_OUT_RATE_HZ=10
  LOG_LEVEL=INFO
"""

import os, time, asyncio, logging, struct
from dataclasses import dataclass
from typing import Optional

import serial           # pip install pyserial
import grpc             # pip install grpcio

from pathlib import Path
import sys
# sys.path.insert(0, str(Path(__file__).resolve().parent / "proto_py"))

import sys
sys.path.insert(0, "/home/admin/krakensdr/doa/backend")
import kraken_pb2 as pb
import kraken_pb2_grpc as pb_grpc
from google.protobuf.empty_pb2 import Empty

# ----------------- Конфиг -----------------
GRPC_HOST = os.getenv("KRAKEN_HOST", "127.0.0.1")
GRPC_PORT = int(os.getenv("KRAKEN_PORT", "5005"))
GRPC_ENDPOINT = f"{GRPC_HOST}:{GRPC_PORT}"

UART_DEV   = os.getenv("PIXHAWK_UART", "/dev/serial0")
UART_BAUD  = int(os.getenv("PIXHAWK_BAUD", "115200"))

DF_OUT_RATE_HZ = float(os.getenv("DF_OUT_RATE_HZ", "10"))  # частота выдачи DOA в UART
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="[%(asctime)s] %(levelname)s: %(message)s")
log = logging.getLogger("pixhawk-bridge")

# ----------------- Протокол -----------------
PRE1, PRE2 = 0xAA, 0xAB
MSG_DOA    = 0xD0
MSG_SETF   = 0x30
MSG_ACKF   = 0x31
MSG_HB     = 0xC0

def pack_frame(msg_id: int, payload: bytes=b"") -> bytes:
    ln = len(payload) & 0xFF
    chk = (msg_id + ln + sum(payload)) & 0xFF
    return bytes([PRE1, PRE2, msg_id, ln]) + payload + bytes([chk])

def unpack_frame(buf: bytearray):
    """
    Ищет и вырезает первый корректный кадр из буфера.
    Возвращает (msg_id, payload) или None.
    """
    i, n = 0, len(buf)
    while i + 4 <= n:
        if buf[i] == PRE1 and buf[i+1] == PRE2:
            if i + 4 > n:
                break
            msg_id = buf[i+2]
            ln     = buf[i+3]
            end    = i + 4 + ln + 1
            if end > n:
                break
            payload = bytes(buf[i+4:i+4+ln])
            chk     = buf[i+4+ln]
            if ((msg_id + ln + sum(payload)) & 0xFF) == chk:
                del buf[:end]
                return msg_id, payload
            else:
                i += 1
                continue
        i += 1
    if i > 0:
        del buf[:i]
    return None

def az_to_cdeg(az_deg: float) -> int:
    a = (az_deg % 360.0 + 360.0) % 360.0
    if a > 180.0:
        a -= 360.0
    return int(round(a * 100.0))

def el_to_cdeg(el_deg: float) -> int:
    e = max(-90.0, min(90.0, el_deg))
    return int(round(e * 100.0))

def conf_byte(conf_0_1: Optional[float], snr: Optional[float]) -> int:
    if conf_0_1 is not None:
        return int(max(0, min(255, round(conf_0_1 * 255))))
    # fallback по SNR: [-5..+20] dB -> [0..255]
    x = ((snr or 0.0) + 5.0) / 25.0
    return int(max(0, min(255, round(x * 255))))

def make_doa_payload(az_deg: float, el_deg: float, conf01: Optional[float], snr: Optional[float]) -> bytes:
    return struct.pack("<hhBB", int(az_deg), int(el_deg), conf_byte(conf01, snr), 0)
    # return struct.pack("<hhBB", az_to_cdeg(az_deg), el_to_cdeg(el_deg), conf_byte(conf01, snr), 0)

# ----------------- gRPC клиент -----------------
class KrakenClient:
    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.ch = None
        self.stub = None

    async def connect(self):
        if pb is None or pb_grpc is None:
            raise RuntimeError("Нет Python-стабов gRPC. Сгенерируйте your_kraken_pb2(.grpc).py из вашего .proto.")
        self.ch = grpc.aio.insecure_channel(self.endpoint)
        # self.stub = pb_grpc.KrakenGrpcStub(self.ch)  # имя сервиса из вашего .proto
        self.stub = pb_grpc.KrakenStub(self.ch)

    async def set_freq(self, hz: float) -> bool:
        try:
            resp = await self.stub.setDaqFrequency(pb.SetDAQFrequency(freq=float(hz / 1e6)))
            _ = getattr(resp, "freq", None)  # сервер может эхо-вернуть freq
            return True
        except Exception as e:
            log.error("gRPC setDaqFrequency failed: %s", e)
            return False

    async def doa_stream(self):
        async for msg in self.stub.getDoaResult(Empty()):
            dests = msg.res.destinations  # repeated DOAAngles { float a; float b; }
            if not dests:
                continue  # нет целей — пропускаем кадр
            d0 = dests[0]                 # при желании выбери лучшую цель: min(dests, key=lambda x: abs(x.b))
            az = float(d0.a)              # градусы
            el = float(d0.b)              # градусы
            yield az, el, 1.0, None       # conf=1.0 (пока в proto нет), snr=None

# ----------------- Мост -----------------
@dataclass
class State:
    last_tx: float = 0.0
    freq_hz: Optional[int] = None

class Bridge:
    def __init__(self):
        self.state = State()
        self.ser = serial.Serial(UART_DEV, UART_BAUD, timeout=0)
        self.buf = bytearray()
        self.kraken = KrakenClient(GRPC_ENDPOINT)

    async def run(self):
        await self.kraken.connect()
        log.info("gRPC=%s; UART=%s @ %d", GRPC_ENDPOINT, UART_DEV, UART_BAUD)
        await asyncio.gather(self.task_uart_rx(), self.task_doa_tx())

    async def task_uart_rx(self):
        loop = asyncio.get_running_loop()
        while True:
            b = await loop.run_in_executor(None, self.ser.read, 64)
            if not b:
                await asyncio.sleep(0.002)
                continue
            self.buf.extend(b)
            while True:
                got = unpack_frame(self.buf)
                if not got:
                    break
                msg_id, payload = got
                if msg_id == MSG_SETF and len(payload) == 4:
                    (hz,) = struct.unpack("<I", payload)
                    await self._handle_setf(hz)

    async def _handle_setf(self, hz: int):
        self.state.freq_hz = hz
        ok = await self.kraken.set_freq(float(hz))
        ack = struct.pack("<IB", hz, 1 if ok else 0)
        self.ser.write(pack_frame(MSG_ACKF, ack))

    async def task_doa_tx(self):
        min_dt = 1.0 / max(DF_OUT_RATE_HZ, 0.1)
        async for az, el, conf01, snr in self.kraken.doa_stream():
            now = time.time()
            if now - self.state.last_tx < min_dt:
                continue
            self.state.last_tx = now
            az = az - 90
            payload = make_doa_payload(az, el, conf01, snr)
            log.debug("TX DOA deg: az=%.2f el=%.2f conf=%.2f", az, el, conf01 if conf01 is not None else -1)
            self.ser.write(pack_frame(MSG_DOA, payload))

async def _amain():
    br = Bridge()
    await br.run()

if __name__ == "__main__":
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        pass
