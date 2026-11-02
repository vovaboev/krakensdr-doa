package com.kraken.doa.service

import org.springframework.stereotype.Service

/**
 * Singleton Spring-бин для хранения состояния между страницами.
 * Vaadin при навигации пересоздаёт View, поэтому локальные поля теряются.
 * Здесь всё живёт, пока работает приложение.
 */
@Service
class AppStateService {
    @Volatile var daqFrequencyMhz: Float = 600f
    @Volatile var antennaLat: Double = 51.672040    // Воронеж
    @Volatile var antennaLon: Double = 39.184300
    @Volatile var antennaHeadingDeg: Double = 0.0   // НОВОЕ: курс антенны (0 = CH-0 смотрит на Север)
}