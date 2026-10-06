# -*- coding: utf-8 -*-
"""
Протокол совместим с вашим Arduino-кодом:

Передача (send_to_serial):
  0: 0xAA
  1: 0xAB
  2: status (1 байт)
  3..?: freq — по байтам МЛАДШИЙ->СТАРШИЙ, ПОКА c > 0 (как в Arduino: while (c > 0) { Serial.write(c); c >>= 8; })
        ВАЖНО: если freq == 0, байты частоты НЕ передаются (точно как в вашей версии).
  ?: amp (1 байт)
  ?: checksum = (status + сумма отправленных байтов freq + amp) & 0xFF

Приём (receive_from_serial):
  Ожидаем поток, ищем подпоследовательность 0xAA 0xAB, затем читаем РОВНО 5 следующих байт:
    start_L, start_H, stop_L, stop_H, checksum
  Проверка checksum: (start_L + start_H + stop_L + stop_H) & 0xFF == checksum
  Если прошла — возвращаем частоты (start, stop) как 16-битные числа (little-endian).

Порты на Raspberry Pi 5:
  Обычно '"/dev/serial0"' указывает на основной UART. Также встречаются '"/dev/ttyAMA0"' или '"/dev/ttyS0"'.
  Включите UART в raspi-config при необходимости.
"""

from typing import Optional, Tuple
import serial


HEADER = b"\xAA\xAB"


def open_serial(
    port: str = "/dev/serial0",
    baudrate: int = 115200,
    read_timeout: float = 0.05,
) -> serial.Serial:
    """
    Открыть UART-порт. read_timeout — таймаут чтения (сек). 0 — неблокирующий режим.
    """
    ser = serial.Serial(
        port=port,
        baudrate=baudrate,
        timeout=read_timeout,
        write_timeout=1.0,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        bytesize=serial.EIGHTBITS,
    )
    return ser


def send_to_serial(ser: serial.Serial, status: int, freq: int, amp: int) -> None:
    """
    Полный аналог вашей Arduino-функции send_to_serial().

    - Отправляет заголовок 0xAA 0xAB
    - status: 1 байт
    - freq: переменное число байт (LSB-first), пока c > 0 (если freq==0 — байты частоты не идут)
    - amp: 1 байт
    - checksum: сумма status + всех отправленных байтов freq + amp (mod 256)
    """
    if not ser.writable():
        raise IOError("Serial port is not writable")

    pkt = bytearray()
    pkt += HEADER

    status_b = status & 0xFF
    pkt.append(status_b)

    # Вычисление и упаковка freq "как на Arduino": LSB-first, пока c > 0
    checksum = status_b
    c = int(freq)
    while c > 0:
        b = c & 0xFF
        pkt.append(b)
        checksum = (checksum + b) & 0xFF
        c >>= 8

    amp_b = amp & 0xFF
    pkt.append(amp_b)
    checksum = (checksum + amp_b) & 0xFF

    pkt.append(checksum & 0xFF)

    ser.write(pkt)
    ser.flush()  # убедимся, что ушло


class SerialReceiver:
    """
    Приёмник для пакетов формата:
      0xAA 0xAB  start_L start_H  stop_L stop_H  checksum
    Возвращает (frequencyStart, frequencyStop) при валидной контрольной сумме.
    Сохраняет внутренний буфер между вызовами (удобно вызывать в цикле).
    """

    def __init__(self, ser: serial.Serial):
        self.ser = ser
        self._rxbuf = bytearray()

    def _fill_buffer(self) -> None:
        n = self.ser.in_waiting
        if n > 0:
            self._rxbuf += self.ser.read(n)

    def receive_from_serial(self) -> Optional[Tuple[int, int]]:
        """
        Аналог вашей resive_from_serial(double &frequencyStart, double &frequencyStop),
        но возвращает int-значения (Hz) либо None, если полного пакета пока нет.
        """
        if not self.ser.readable():
            raise IOError("Serial port is not readable")

        # Подчитаем всё, что есть в драйвере
        self._fill_buffer()

        # Ищем заголовок
        while True:
            idx = self._rxbuf.find(HEADER)
            if idx < 0:
                # Держим хвост из одного байта 0xAA — вдруг это начало заголовка
                if len(self._rxbuf) > 1:
                    self._rxbuf = self._rxbuf[-1:]
                return None

            # После заголовка нам нужно ещё 5 байт (start_L, start_H, stop_L, stop_H, checksum)
            need_len = idx + 2 + 5
            if len(self._rxbuf) < need_len:
                # Пакет ещё не дошёл
                return None

            start_L = self._rxbuf[idx + 2]
            start_H = self._rxbuf[idx + 3]
            stop_L  = self._rxbuf[idx + 4]
            stop_H  = self._rxbuf[idx + 5]
            chk     = self._rxbuf[idx + 6]

            calc = (start_L + start_H + stop_L + stop_H) & 0xFF

            # Сразу вырежем обработанный префикс (с валидностью разберёмся ниже)
            del self._rxbuf[: idx + 7]

            if calc == chk:
                frequencyStart = (start_H << 8) | start_L
                frequencyStop  = (stop_H  << 8) | stop_L
                return frequencyStart, frequencyStop
            else:
                # Контрольная сумма не сошлась — продолжаем искать следующий заголовок
                # Цикл while попробует найти следующую последовательность HEADER в оставшемся буфере
                # (ничего не возвращаем в этот вызов)
                continue


# ---------------------------- Пример использования ----------------------------
if __name__ == "__main__":
    # Откройте нужный порт/скорость под свою схему
    ser = open_serial(port="/dev/serial0", baudrate=115200, read_timeout=0.02)

    # Пример отправки — эквивалент вашей send_to_serial(status, freq, amp)
    # Частота 10000 Гц будет отправлена как два байта: 0x10 0x27 (LSB->MSB),
    # если freq=0 — байты частоты НЕ пойдут (строго как в Arduino-версии).
    send_to_serial(ser, status=0x01, freq=410, amp=0x32)

    # Пример приёма — эквивалент вашей resive_from_serial(...)
    rx = SerialReceiver(ser)
    # В обычном коде это будет в цикле:
    for _ in range(200):  # условная небольшая попытка «популлить» данные
        pair = rx.receive_from_serial()
        if pair is not None:
            f_start, f_stop = pair
            print(f"Got start={f_start} Hz, stop={f_stop} Hz")
            break