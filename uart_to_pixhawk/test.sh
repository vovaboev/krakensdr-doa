#!/bin/bash

stty -F /dev/serial0 115200 raw -echo -ixon -ixoff
cat < /dev/serial0 &
printf "PING\r\n" > /dev/serial0
# Должно отобразиться "PING" с CRLF
kill %1