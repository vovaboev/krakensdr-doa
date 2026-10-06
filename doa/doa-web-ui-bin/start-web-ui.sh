#!/bin/bash

# Завершить Java-процесс при остановке скрипта
trap 'kill -TERM $JAVA_PID' TERM INT

# Запуск Java в фоне с сохранением PID
java -jar doa-0.0.3.jar --server.port=80 --kraken.ip=127.0.0.1 &
JAVA_PID=$!

# Ждать завершения (или сигнала)
wait $JAVA_PID

# Было так
# #! /bin/bash
# java -jar doa-0.0.3.jar --server.port=80 --kraken.ip=127.0.0.1