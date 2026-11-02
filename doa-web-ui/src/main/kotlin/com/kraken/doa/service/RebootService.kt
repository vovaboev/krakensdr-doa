package com.kraken.doa.service

import org.slf4j.LoggerFactory
import org.springframework.stereotype.Service

@Service
class RebootService {
    private val log = LoggerFactory.getLogger(RebootService::class.java)

    fun restartAll() {
        try {
            log.info("Initiating system restart via transient systemd unit...")
            // Запускаем скрипт как отдельный юнит systemd, он не умрет вместе с Java
            val pb = ProcessBuilder(
                "sudo", "systemd-run", "--unit=kraken-reboot", 
                "/home/admin/krakensdr/restart_services.sh"
            )
            pb.redirectErrorStream(true)
            pb.start()
        } catch (e: Exception) {
            log.error("Failed to restart services", e)
        }
    }
}