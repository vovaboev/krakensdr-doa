import serial, time
print("начало работы")
ser = serial.Serial('/dev/serial0', baudrate=115200, timeout=1)
print("Открыли порт")
i = 0
while True:
    print(f"status=33, freq=410, amp=90 (#{i})")
    # [0xAA, 0xAB, 0x21, 0x9A, 0x01, 0x5A, 0x16]
    packet = b'\xAA\xAB\x21\x9A\x01\x5A\x16'
    ser.write(packet)
    i += 1
    time.sleep(0.5)