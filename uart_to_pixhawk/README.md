Протокол UART (V2)

Кадр:

+--------+--------+--------+--------+---------------- len байт ---------------+----------+
| 0xAA   | 0xAB   | msg_id |  len   | payload                                  | checksum |
+--------+--------+--------+--------+------------------------------------------+----------+


checksum = (msg_id + len + sum(payload)) & 0xFF

Порядок полей в payload — little-endian.

Сообщения:

0xD0 — DOA (результат пеленгации)

payload: <int16 az_cdeg><int16 el_cdeg><uint8 conf_u8><uint8 flags>

az_cdeg — азимут в сотых градуса, диапазон [-18000…+18000] (если нужно [0…36000), нормализуйте на FC if (az_deg < 0) az_deg += 360;).

el_cdeg — угол места в сотых градуса, [-9000…+9000].

conf_u8 — доверие 0…255 (0.0…1.0 → 0…255).

flags — резерв (пока 0).

0x30 — SETF (частота от FC к RPi)
payload: <uint32 freq_hz>

0x31 — ACKF (подтверждение от RPi к FC)
payload: <uint32 freq_hz><uint8 ok> (1/0)

0xC0 — HB (heartbeat, опционально)
payload: пусто.



install_pixhawk_kraken_service.sh
# 1) сохранить
nano install_pixhawk_kraken_service.sh
# вставьте скрипт, сохраните

# 2) сделать исполняемым
chmod +x install_pixhawk_kraken_service.sh

# 3) запустить (желательно через sudo)
sudo ./install_pixhawk_kraken_service.sh