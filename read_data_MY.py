import socket

UDP_IP = "0.0.0.0"  # Слушаем все интерфейсы
UDP_PORT = 8081

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))

while True:
    print(f"Receiv")
    data, addr = sock.recvfrom(1024)  # Буфер 1024 байта
    print(f"Received: {data.hex()}")  # Вывод в hex