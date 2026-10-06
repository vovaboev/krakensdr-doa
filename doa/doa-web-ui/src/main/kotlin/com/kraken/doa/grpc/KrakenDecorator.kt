package com.kraken.doa.grpc

import com.google.protobuf.Empty
import com.karaken.AntennaPresetsResponse
import com.karaken.ClassificationData
import com.karaken.DOAResult
import com.karaken.KrakenGrpc
import com.karaken.MusicSpectrumData
import com.karaken.SetAntennaPresetRequest
import com.karaken.SetDAQFrequency
import com.karaken.SetRecordingRequest
import com.karaken.SetRecordingResponse
import com.karaken.SpectrumData
import io.grpc.ManagedChannel
import io.grpc.ManagedChannelBuilder
import io.grpc.stub.StreamObserver
import jakarta.annotation.PreDestroy
import org.slf4j.LoggerFactory
import org.springframework.beans.factory.annotation.Value
import org.springframework.stereotype.Service
import java.util.concurrent.TimeUnit
import java.util.function.Consumer

open class ProtoStreamObserver<T>(
    private val name: String,
    private val onData: Consumer<T>? = null
) : StreamObserver<T> {

    private val log = LoggerFactory.getLogger(ProtoStreamObserver::class.java)

    override fun onNext(p0: T?) {
        if (onData != null && p0 != null) {
            try {
                onData.accept(p0)
            } catch (e: Exception) {
                log.error("[{}] Ошибка при обработке данных: {}", name, e.message, e)
            }
        }
    }

    override fun onError(p0: Throwable?) {
        log.error("[{}] Ошибка gRPC-потока: {}", name, p0?.message, p0)
    }

    override fun onCompleted() {
        log.info("[{}] Поток завершён", name)
    }
}

class DoaResultStreamObserver(onDOAResult: Consumer<DOAResult>) :
    ProtoStreamObserver<DOAResult>("DOA", onDOAResult)

class SpectrumStreamObserver(onSpectrum: Consumer<SpectrumData>) :
    ProtoStreamObserver<SpectrumData>("Spectrum", onSpectrum)

class ClassificationStreamObserver(onClassification: Consumer<ClassificationData>) :
    ProtoStreamObserver<ClassificationData>("Classification", onClassification)

class MusicSpectrumStreamObserver(onMusicSpectrum: Consumer<MusicSpectrumData>) :
    ProtoStreamObserver<MusicSpectrumData>("MusicSpectrum", onMusicSpectrum)

@Service
class KrakenDecorator {

    private val log = LoggerFactory.getLogger(KrakenDecorator::class.java)

    @Value("\${kraken.ip:localhost}")
    private val krakenIp: String = "localhost"

    @Value("\${kraken.port:5005}")
    private val krakenPort: Int = 5005

    @Value("\${kraken.timeout-ms:2000}")
    private val timeoutMs: Long = 2000

    private val controlChannel: ManagedChannel by lazy {
        ManagedChannelBuilder.forAddress(krakenIp, krakenPort).usePlaintext().build()
    }

    private var daoResultChannel: ManagedChannel? = null
    private var spectrumChannel: ManagedChannel? = null
    private var classificationChannel: ManagedChannel? = null
    private var musicSpectrumChannel: ManagedChannel? = null

    fun stop() {
        try {
            val stub = KrakenGrpc.newBlockingStub(controlChannel)
                .withDeadlineAfter(timeoutMs, TimeUnit.MILLISECONDS)
            val response = stub.stop(Empty.newBuilder().build())
            if (response != null) {
                log.info("Команда stop отправлена")
            }
        } catch (e: Exception) {
            log.error("Не удалось отправить stop: {}", e.message, e)
        }
    }

    fun setFrequency(freq: Float) {
        try {
            val stub = KrakenGrpc.newBlockingStub(controlChannel)
                .withDeadlineAfter(timeoutMs, TimeUnit.MILLISECONDS)
            val request = SetDAQFrequency.newBuilder().setFreq(freq).build()
            val response = stub.setDaqFrequency(request)
            if (response != null) {
                log.debug("DAQ Freq: {} Hz", response.freq)
            }
        } catch (e: Exception) {
            log.error("Не удалось установить частоту {}: {}", freq, e.message)
        }
    }

    fun setRecording(enabled: Boolean, filename: String = ""): SetRecordingResponse {
        return try {
            val stub = KrakenGrpc.newBlockingStub(controlChannel)
                .withDeadlineAfter(timeoutMs, TimeUnit.MILLISECONDS)
            val request = SetRecordingRequest.newBuilder()
                .setEnabled(enabled)
                .setFilename(filename)
                .build()
            val response = stub.setRecording(request)
            log.info(
                "setRecording(enabled={}) → path={}, frames={}",
                response.enabled, response.path, response.framesWritten
            )
            response
        } catch (e: Exception) {
            log.error("Ошибка setRecording: {}", e.message, e)
            SetRecordingResponse.getDefaultInstance()
        }
    }

    fun getAntennaPresets(): AntennaPresetsResponse {
        return try {
            val stub = KrakenGrpc.newBlockingStub(controlChannel)
                .withDeadlineAfter(timeoutMs, TimeUnit.MILLISECONDS)
            stub.getAntennaPresets(Empty.newBuilder().build())
        } catch (e: Exception) {
            log.error("Ошибка getAntennaPresets: {}", e.message, e)
            AntennaPresetsResponse.getDefaultInstance()
        }
    }

    fun setAntennaPreset(key: String): AntennaPresetsResponse {
        return try {
            val stub = KrakenGrpc.newBlockingStub(controlChannel)
                .withDeadlineAfter(timeoutMs, TimeUnit.MILLISECONDS)
            val request = SetAntennaPresetRequest.newBuilder().setKey(key).build()
            val response = stub.setAntennaPreset(request)
            log.info("setAntennaPreset(key={}) → current={}, success={}",
                key, response.current, response.success)
            response
        } catch (e: Exception) {
            log.error("Ошибка setAntennaPreset: {}", e.message, e)
            AntennaPresetsResponse.getDefaultInstance()
        }
    }

    fun subscribeToDaoResult(callback: Consumer<DOAResult>) {
        cancelSubscriptionToDaoResult()
        daoResultChannel = ManagedChannelBuilder.forAddress(krakenIp, krakenPort).usePlaintext().build()
        val stub = KrakenGrpc.newStub(daoResultChannel)
        stub.getDoaResult(Empty.newBuilder().build(), DoaResultStreamObserver(callback))
        log.info("Подписка на DOA-результаты открыта")
    }

    fun cancelSubscriptionToDaoResult() {
        daoResultChannel?.let {
            it.shutdown()
            log.info("Подписка на DOA-результаты закрыта")
        }
        daoResultChannel = null
    }

    fun subscribeToSpectrum(callback: Consumer<SpectrumData>) {
        cancelSubscriptionSpectrum()
        spectrumChannel = ManagedChannelBuilder.forAddress(krakenIp, krakenPort).usePlaintext().build()
        val stub = KrakenGrpc.newStub(spectrumChannel)
        stub.getSpectrum(Empty.newBuilder().build(), SpectrumStreamObserver(callback))
        log.info("Подписка на спектр открыта")
    }

    fun cancelSubscriptionSpectrum() {
        spectrumChannel?.let {
            it.shutdown()
            log.info("Подписка на спектр закрыта")
        }
        spectrumChannel = null
    }

    fun subscribeToClassification(callback: Consumer<ClassificationData>) {
        cancelSubscriptionClassification()
        classificationChannel = ManagedChannelBuilder.forAddress(krakenIp, krakenPort).usePlaintext().build()
        val stub = KrakenGrpc.newStub(classificationChannel)
        stub.getClassification(Empty.newBuilder().build(), ClassificationStreamObserver(callback))
        log.info("Подписка на классификацию открыта")
    }

    fun cancelSubscriptionClassification() {
        classificationChannel?.let {
            it.shutdown()
            log.info("Подписка на классификацию закрыта")
        }
        classificationChannel = null
    }

    fun subscribeToMusicSpectrum(callback: Consumer<MusicSpectrumData>) {
        cancelSubscriptionMusicSpectrum()
        musicSpectrumChannel = ManagedChannelBuilder.forAddress(krakenIp, krakenPort).usePlaintext().build()
        val stub = KrakenGrpc.newStub(musicSpectrumChannel)
        stub.getMusicSpectrum(Empty.newBuilder().build(), MusicSpectrumStreamObserver(callback))
        log.info("Подписка на MUSIC-спектр открыта")
    }

    fun cancelSubscriptionMusicSpectrum() {
        musicSpectrumChannel?.let {
            it.shutdown()
            log.info("Подписка на MUSIC-спектр закрыта")
        }
        musicSpectrumChannel = null
    }

    @PreDestroy
    fun shutdown() {
        log.info("Останавливаю KrakenDecorator...")
        cancelSubscriptionToDaoResult()
        cancelSubscriptionSpectrum()
        cancelSubscriptionClassification()
        cancelSubscriptionMusicSpectrum()
        if (!controlChannel.isShutdown) {
            controlChannel.shutdown()
        }
    }
}