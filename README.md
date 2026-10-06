sudo raspi-config

Проверь логи:
dmesg
journalctl -xe
sudo tail -f /var/log/syslog
sudo systemctl status kraken_backend.service
sudo systemctl status kraken_web_ui.service
sudo systemctl restart kraken_backend.service
sudo systemctl restart kraken_web_ui.service
sudo systemctl restart start_heimdall.service
sudo systemctl restart pixhawk-kraken-bridge.service

sudo systemctl stop kraken_backend.service
sudo systemctl stop kraken_web_ui.service
sudo systemctl stop start_heimdall.service
sudo systemctl stop pixhawk-kraken-bridge.service

journalctl -u kraken_backend.service -f
journalctl -u kraken_web_ui.service -f
journalctl -u start_heimdall.service -f
journalctl -u pixhawk-kraken-bridge.service -f

sudo systemctl start krakensdr_web.service
sudo systemctl stop krakensdr_web.service

journalctl -u krakensdr_web -f

# Очистить все логи
sudo journalctl -u kraken_web_ui.service --rotate
sudo journalctl -u kraken_web_ui.service --vacuum-time=1s --no-pager
sudo journalctl -u krakensdr_web.service --rotate
sudo journalctl -u krakensdr_web.service --vacuum-time=1s --no-pager


Проверьте температуру CPU:
vcgencmd measure_temp

chmod [настройки прав] [файл или папка]
chmod +x script.sh

Активация окружения
CONDA_BASE_PATH=$(conda info --base)
source "$CONDA_BASE_PATH/bin/activate" kraken

Проверить статус всех сервисов
systemctl list-units --type=service --all
или только активные:
systemctl list-units --type=service --state=running
Статусы:
loaded — сервис загружен в систему
active (running) — работает
failed — завершился с ошибкой
inactive (dead) — не запущен

Проверьте, занят ли порт 8080:
sudo netstat -tulnp | grep 8080

Создаем/редактируем сервисный файл
sudo nano /etc/systemd/system/krakensdr_web.service

Environment="PATH=/home/admin/miniforge3/envs/kraken/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="PYTHONPATH=/home/admin/krakensdr/krakensdr_doa/_ui/_web_interface/"

[Unit]
Description=KrakenSDR Web Interface
After=network.target

[Service]
User=root
Group=root
WorkingDirectory=/home/admin/krakensdr/
ExecStart=/bin/bash ./kraken_doa_start.sh
ExecStop=/bin/bash ./kraken_doa_stop.sh
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target



Рабочий вариант сервиса!!!!!!
[Unit]
Description=Service for starting Heimdall DAQ subsystem

[Service]
Type=oneshot
WorkingDirectory=/home/admin/krakensdr/heimdall_daq_fw/Firmware
ExecStart=/bin/bash /home/admin/krakensdr/heimdall_daq_fw/Firmware/daq_start_sm.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target