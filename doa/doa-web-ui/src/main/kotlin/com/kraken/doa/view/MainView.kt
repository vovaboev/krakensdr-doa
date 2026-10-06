package com.kraken.doa.view

import com.kraken.doa.grpc.KrakenDecorator
import com.vaadin.flow.component.AttachEvent
import com.vaadin.flow.component.DetachEvent
import com.vaadin.flow.component.UI
import com.vaadin.flow.component.button.Button
import com.vaadin.flow.component.combobox.ComboBox
import com.vaadin.flow.component.confirmdialog.ConfirmDialog
import com.vaadin.flow.component.html.Span
import com.vaadin.flow.component.notification.Notification
import com.vaadin.flow.component.orderedlayout.HorizontalLayout
import com.vaadin.flow.component.orderedlayout.VerticalLayout
import com.vaadin.flow.component.textfield.TextField
import com.vaadin.flow.router.Route
import org.vaadin.pekkam.Canvas
import java.util.Locale

@Route("")
class MainView(private val krakenDecorator: KrakenDecorator) : VerticalLayout() {

    companion object {
        private const val TARGET_CANVAS_SIZE = 400
        private const val SPECTRUM_CANVAS_WIDTH = 800
        private const val SPECTRUM_CANVAS_HEIGHT = 300
        private const val CROSS_HALF_SIZE = 5.0
        private const val AZIMUTH_OFFSET_DEG = 90.0f
        private const val AZIMUTH_RANGE_DEG = 70.0
        private const val ELEVATION_RANGE_DEG = 50.0
        private const val CANVAS_MARGIN = 0.9

        // Троттлинг отрисовки: не чаще чем раз в 500 мс
        private const val DRAW_THROTTLE_MS = 500L
    }

    private val stopButton = Button("Остановить сервер")
    private val recordButton = Button("Начать запись")
    private var isRecording = false

    private val antennaSelect = ComboBox<String>()
    private var currentAntennaKey: String? = null

    private val doaResultLayout = HorizontalLayout()
    private val doaFreqTitle = Span("Частота")
    private val doaFreqValue = Span("-")
    private val doaDestLayout = VerticalLayout()
    private val classificationResultLayout = VerticalLayout()

    private val settingsLayout = HorizontalLayout()
    private val daqFrequencyText = TextField()
    private val daqFrequencyApply = Button("Применить")

    private var attachedUi: UI? = null
    private var subscriptionsActive = false

    private val targetCanvas = Canvas(TARGET_CANVAS_SIZE, TARGET_CANVAS_SIZE)
    private val spectrumCanvas = Canvas(SPECTRUM_CANVAS_WIDTH, SPECTRUM_CANVAS_HEIGHT)

    override fun onAttach(attachEvent: AttachEvent?) {
        attachedUi = attachEvent?.ui
        if (!subscriptionsActive) {
            openSubscriptions()
            subscriptionsActive = true
        }
    }

    override fun onDetach(detachEvent: DetachEvent?) {
        cancelSubscriptions()
        attachedUi = null
    }

    private fun cancelSubscriptions() {
        krakenDecorator.cancelSubscriptionToDaoResult()
        krakenDecorator.cancelSubscriptionSpectrum()
        krakenDecorator.cancelSubscriptionClassification()
        subscriptionsActive = false
    }

    private fun openSubscriptions() {
        // ---- Подписка на классификацию ----
        krakenDecorator.subscribeToClassification { result ->
            attachedUi?.access {
                classificationResultLayout.removeAll()
                classificationResultLayout.add(Span("Результаты классификации"))
                for (i in result.namesList.indices) {
                    if (i < result.probsList.size) {
                        classificationResultLayout.add(
                            Span("${result.namesList[i]}: ${result.probsList[i]}")
                        )
                    }
                }
            }
        }

        // ---- Подписка на DOA с троттлингом ----
        var lastDoaDraw = 0L
        krakenDecorator.subscribeToDaoResult { result ->
            val now = System.currentTimeMillis()
            if (now - lastDoaDraw < DRAW_THROTTLE_MS) return@subscribeToDaoResult
            lastDoaDraw = now

            attachedUi?.access {
                doaFreqValue.text = String.format(Locale.US, "%.3f МГц", result.freq / 1e6)
                doaDestLayout.removeAll()
                doaDestLayout.add(Span("Направления на сигналы"))
                result.res.destinationsList.forEach {
                    val azimuth = it.a - AZIMUTH_OFFSET_DEG
                    val elevation = it.b
                    doaDestLayout.add(
                        Span(String.format(Locale.US, "[%.2f, %.2f]", azimuth, elevation))
                    )
                }

                if (result.res.destinationsList.isNotEmpty()) {
                    val first = result.res.destinationsList[0]
                    val azimuth = first.a - AZIMUTH_OFFSET_DEG
                    val elevation = first.b

                    val ctx = targetCanvas.context
                    ctx.save()
                    ctx.clearRect(
                        0.0, 0.0,
                        TARGET_CANVAS_SIZE.toDouble(), TARGET_CANVAS_SIZE.toDouble()
                    )
                    ctx.beginPath()
                    ctx.setStrokeStyle("blue")
                    ctx.rect(
                        1.0, 1.0,
                        (TARGET_CANVAS_SIZE - 2).toDouble(),
                        (TARGET_CANVAS_SIZE - 2).toDouble()
                    )

                    val xCenter = (azimuth.toDouble() + AZIMUTH_RANGE_DEG / 2) / AZIMUTH_RANGE_DEG *
                            TARGET_CANVAS_SIZE.toDouble() * CANVAS_MARGIN
                    val yCenter = (elevation.toDouble() + ELEVATION_RANGE_DEG / 2) / ELEVATION_RANGE_DEG *
                            TARGET_CANVAS_SIZE.toDouble() * CANVAS_MARGIN

                    ctx.setStrokeStyle("red")
                    ctx.moveTo(xCenter - CROSS_HALF_SIZE, yCenter)
                    ctx.lineTo(xCenter + CROSS_HALF_SIZE, yCenter)
                    ctx.moveTo(xCenter, yCenter - CROSS_HALF_SIZE)
                    ctx.lineTo(xCenter, yCenter + CROSS_HALF_SIZE)
                    ctx.closePath()
                    ctx.stroke()
                    ctx.restore()
                }
            }
        }

        // ---- Подписка на спектр с троттлингом ----
        var lastSpectrumDraw = 0L
        krakenDecorator.subscribeToSpectrum { spectrum ->
            val now = System.currentTimeMillis()
            if (now - lastSpectrumDraw < DRAW_THROTTLE_MS) return@subscribeToSpectrum
            lastSpectrumDraw = now

            attachedUi?.access {
                if (spectrum.specList.isNotEmpty()) {
                    val specListSize = spectrum.specList.size.toDouble()
                    val shortSpectrum = FloatArray(SPECTRUM_CANVAS_WIDTH) { -1000.0f }
                    for (i in 0 until spectrum.specList.size) {
                        val x = ((i.toDouble() / specListSize) * shortSpectrum.size.toDouble()).toInt()
                        if (shortSpectrum[x] < spectrum.specList[i]) {
                            shortSpectrum[x] = spectrum.specList[i]
                        }
                    }

                    val ctx = spectrumCanvas.context
                    ctx.save()
                    ctx.clearRect(
                        0.0, 0.0,
                        SPECTRUM_CANVAS_WIDTH.toDouble(),
                        SPECTRUM_CANVAS_HEIGHT.toDouble()
                    )
                    ctx.beginPath()
                    ctx.setStrokeStyle("blue")
                    ctx.rect(
                        1.0, 1.0,
                        (SPECTRUM_CANVAS_WIDTH - 2).toDouble(),
                        (SPECTRUM_CANVAS_HEIGHT - 2).toDouble()
                    )
                    ctx.setStrokeStyle("red")
                    for (i in shortSpectrum.indices) {
                        val x = i.toDouble() / shortSpectrum.size.toDouble() * SPECTRUM_CANVAS_WIDTH.toDouble()
                        val y = (1.0 - (shortSpectrum[i] + 100.0f).toDouble() / 80.0) *
                                SPECTRUM_CANVAS_HEIGHT.toDouble()
                        if (i == 0) ctx.moveTo(x, y) else ctx.lineTo(x, y)
                    }
                    ctx.closePath()
                    ctx.stroke()
                    ctx.restore()
                }
            }
        }
    }

    init {
        doaResultLayout.add(doaFreqTitle)
        doaResultLayout.add(doaFreqValue)
        doaResultLayout.add(doaDestLayout)
        doaResultLayout.add(classificationResultLayout)

        settingsLayout.add(Span("Центральная частота кракена"))
        settingsLayout.add(daqFrequencyText)
        settingsLayout.add(Span("МГц"))
        settingsLayout.add(daqFrequencyApply)

        antennaSelect.label = "Конфигурация антенны"
        antennaSelect.setWidth("300px")
        antennaSelect.isEnabled = false
        antennaSelect.placeholder = "Загрузка..."

        add(doaResultLayout)
        add(targetCanvas)
        add(Span("Спектр"))
        add(spectrumCanvas)
        add(settingsLayout)
        add(antennaSelect)

        val musicSpectrumButton = Button("MUSIC-спектр")
        musicSpectrumButton.themeName = "secondary"
        musicSpectrumButton.addClickListener {
            UI.getCurrent().navigate("music-spectrum")
        }
        add(musicSpectrumButton)

        add(recordButton)
        add(stopButton)

        stopButton.themeName = "primary error"
        recordButton.themeName = "success"

        // ---- Асинхронная загрузка пресетов — UI не блокируется ----
        loadAntennaPresetsAsync()

        // ---- Смена пресета ----
        antennaSelect.addValueChangeListener { event ->
            val newKey = event.value ?: return@addValueChangeListener
            if (newKey == currentAntennaKey) return@addValueChangeListener

            val oldDisplay = event.oldValue ?: "—"
            ConfirmDialog().apply {
                setHeader("Сменить конфигурацию антенны?")
                setText(
                    "Вы переключаетесь с '$oldDisplay' на " +
                    "'${displayNameFor(newKey)}'.\n\n" +
                    "Убедитесь, что физически подключён именно этот блок антенн."
                )
                setConfirmText("Переключить")
                setCancelText("Отмена")
                setCancelable(true)

                addConfirmListener {
                    // gRPC-вызов в фоновом потоке, чтобы не блокировать UI
                    Thread {
                        val response = try {
                            krakenDecorator.setAntennaPreset(newKey)
                        } catch (e: Exception) {
                            null
                        }
                        attachedUi?.access {
                            if (response != null && response.success) {
                                currentAntennaKey = response.current
                                Notification.show(
                                    "Антенна переключена: $newKey",
                                    3000,
                                    Notification.Position.TOP_CENTER
                                )
                            } else {
                                Notification.show(
                                    "Не удалось переключить антенну",
                                    5000,
                                    Notification.Position.TOP_CENTER
                                ).apply { themeName = "error" }
                                antennaSelect.value = currentAntennaKey
                            }
                        }
                    }.start()
                }

                addCancelListener {
                    antennaSelect.value = currentAntennaKey
                }

                open()
            }
        }

        // ---- Остановка сервера ----
        stopButton.addClickListener {
            ConfirmDialog().apply {
                setHeader("Остановить сервер?")
                setText("Бэкенд перестанет обрабатывать данные. Продолжить?")
                setConfirmText("Остановить")
                setCancelable(true)
                addConfirmListener {
                    Thread {
                        try { krakenDecorator.stop() } catch (_: Exception) {}
                    }.start()
                }
                open()
            }
        }

        // ---- Запись IQ ----
        recordButton.addClickListener {
            Thread {
                val wantToStart = !isRecording
                val response = try {
                    krakenDecorator.setRecording(wantToStart)
                } catch (e: Exception) {
                    null
                }
                attachedUi?.access {
                    if (response == null) {
                        Notification.show("Ошибка записи", 5000, Notification.Position.TOP_CENTER)
                        return@access
                    }
                    isRecording = response.enabled
                    if (isRecording) {
                        recordButton.text = "Остановить запись"
                        recordButton.themeName = "error"
                        Notification.show(
                            "Запись начата: ${response.path}",
                            5000,
                            Notification.Position.TOP_CENTER
                        )
                    } else {
                        recordButton.text = "Начать запись"
                        recordButton.themeName = "success"
                        Notification.show(
                            "Запись остановлена. Сохранено ${response.framesWritten} кадров",
                            7000,
                            Notification.Position.TOP_CENTER
                        )
                    }
                }
            }.start()
        }

        // ---- Применение частоты ----
        daqFrequencyApply.addClickListener {
            val value = daqFrequencyText.value?.toFloatOrNull()
            if (value == null || value <= 0f) {
                Notification.show("Введите корректную частоту в МГц")
                return@addClickListener
            }
            Thread {
                try { krakenDecorator.setFrequency(value) } catch (_: Exception) {}
            }.start()
        }
    }

    /**
     * Асинхронная загрузка пресетов. Не блокирует UI-поток Vaadin.
     */
    private fun loadAntennaPresetsAsync() {
        Thread {
            val response = try {
                krakenDecorator.getAntennaPresets()
            } catch (e: Exception) {
                null
            }
            attachedUi?.access {
                if (response != null && response.availableList.isNotEmpty()) {
                    val keys = response.availableList.map { it.key }
                    antennaSelect.setItems(keys)
                    antennaSelect.setItemLabelGenerator { key ->
                        response.availableList.find { it.key == key }?.displayName ?: key
                    }
                    currentAntennaKey = response.current
                    antennaSelect.value = response.current
                    antennaSelect.isEnabled = true
                    antennaSelect.placeholder = null
                } else {
                    antennaSelect.isEnabled = false
                    antennaSelect.placeholder = "Пресеты недоступны"
                }
            }
        }.start()
    }

    private fun displayNameFor(key: String): String {
        return try {
            val response = krakenDecorator.getAntennaPresets()
            response.availableList.find { it.key == key }?.displayName ?: key
        } catch (e: Exception) {
            key
        }
    }
}