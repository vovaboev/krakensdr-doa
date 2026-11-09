package com.kraken.doa.view

import com.kraken.doa.grpc.KrakenDecorator
import com.kraken.doa.service.AppStateService
import com.kraken.doa.service.RebootService
import com.vaadin.flow.component.AttachEvent
import com.vaadin.flow.component.DetachEvent
import com.vaadin.flow.component.UI
import com.vaadin.flow.component.button.Button
import com.vaadin.flow.component.combobox.ComboBox
import com.vaadin.flow.component.confirmdialog.ConfirmDialog
import com.vaadin.flow.component.html.Span
import com.vaadin.flow.component.notification.Notification
import com.vaadin.flow.component.orderedlayout.FlexComponent.Alignment
import com.vaadin.flow.component.orderedlayout.FlexComponent.JustifyContentMode
import com.vaadin.flow.component.orderedlayout.HorizontalLayout
import com.vaadin.flow.component.orderedlayout.VerticalLayout
import com.vaadin.flow.component.progressbar.ProgressBar
import com.vaadin.flow.component.textfield.TextField
import com.vaadin.flow.router.Route
import org.vaadin.pekkam.Canvas
import java.util.Locale

@Route("")
class MainView(
    private val krakenDecorator: KrakenDecorator,
    private val appState: AppStateService,
    private val rebootService: RebootService
) : VerticalLayout() {

    companion object {
        private const val TARGET_CANVAS_SIZE = 400
        private const val SPECTRUM_CANVAS_WIDTH = 800
        private const val SPECTRUM_CANVAS_HEIGHT = 300
        private const val CROSS_HALF_SIZE = 5.0
        private const val AZIMUTH_OFFSET_DEG = 90.0f
        private const val AZIMUTH_RANGE_DEG = 70.0
        private const val ELEVATION_RANGE_DEG = 50.0
        private const val CANVAS_MARGIN = 0.9
        private const val DRAW_THROTTLE_MS = 500L
    }

    private val stopButton = Button("Остановить сервер")
    private val rebootButton = Button("Перезагрузить систему")
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

    private val targetCanvas = Canvas(TARGET_CANVAS_SIZE, TARGET_CANVAS_SIZE)
    private val spectrumCanvas = Canvas(SPECTRUM_CANVAS_WIDTH, SPECTRUM_CANVAS_HEIGHT)

    // ЭЛЕМЕНТЫ ИНДИКАТОРА ЗАГРУЗКИ (ИСПРАВЛЕНО)
    private val loadingLayout = VerticalLayout().apply {
        isVisible = true
        setSizeFull()
        setAlignItems(Alignment.CENTER)
        setJustifyContentMode(JustifyContentMode.CENTER)
    }
    private val loadingText = Span("Ожидание калибровки KrakenSDR...")
    private val progressBar = ProgressBar().apply {
        isIndeterminate = true
        setWidth("300px")
    }

    override fun onAttach(attachEvent: AttachEvent?) {
        attachedUi = attachEvent?.ui
        openSubscriptions()
    }

    override fun onDetach(detachEvent: DetachEvent?) {
        cancelSubscriptions()
        attachedUi = null
        try {
            Thread.sleep(100)
        } catch (_: InterruptedException) { }
    }

    private fun cancelSubscriptions() {
        try { krakenDecorator.cancelSubscriptionToDaoResult() } catch (_: Exception) {}
        try { krakenDecorator.cancelSubscriptionSpectrum() } catch (_: Exception) {}
        try { krakenDecorator.cancelSubscriptionClassification() } catch (_: Exception) {}
    }

    private fun openSubscriptions() {
        // ---- Подписка на классификацию ----
        krakenDecorator.subscribeToClassification { result ->
            val ui = attachedUi ?: return@subscribeToClassification
            try {
                ui.access {
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
            } catch (_: Exception) { }
        }

        // ---- Подписка на DOA ----
        var lastDoaDraw = 0L
        krakenDecorator.subscribeToDaoResult { result ->
            val now = System.currentTimeMillis()
            if (now - lastDoaDraw < DRAW_THROTTLE_MS) return@subscribeToDaoResult
            lastDoaDraw = now

            val ui = attachedUi ?: return@subscribeToDaoResult
            try {
                ui.access {
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
                        ctx.clearRect(0.0, 0.0, TARGET_CANVAS_SIZE.toDouble(), TARGET_CANVAS_SIZE.toDouble())
                        ctx.beginPath()
                        ctx.setStrokeStyle("blue")
                        ctx.rect(1.0, 1.0, (TARGET_CANVAS_SIZE - 2).toDouble(), (TARGET_CANVAS_SIZE - 2).toDouble())

                        val xCenter = (azimuth.toDouble() + AZIMUTH_RANGE_DEG / 2) / AZIMUTH_RANGE_DEG * TARGET_CANVAS_SIZE.toDouble() * CANVAS_MARGIN
                        val yCenter = (elevation.toDouble() + ELEVATION_RANGE_DEG / 2) / ELEVATION_RANGE_DEG * TARGET_CANVAS_SIZE.toDouble() * CANVAS_MARGIN

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
            } catch (_: Exception) { }
        }

        // ---- Подписка на спектр (ЗДЕСЬ ПРЯЧЕМ ИНДИКАТОР) ----
        var lastSpectrumDraw = 0L
        krakenDecorator.subscribeToSpectrum { spectrum ->
            val now = System.currentTimeMillis()
            if (now - lastSpectrumDraw < DRAW_THROTTLE_MS) return@subscribeToSpectrum
            lastSpectrumDraw = now

            val ui = attachedUi ?: return@subscribeToSpectrum
            try {
                ui.access {
                    if (spectrum.specList.isNotEmpty()) {
                        // Прячем индикатор загрузки, так как пришли данные!
                        if (loadingLayout.isVisible) {
                            loadingLayout.isVisible = false
                            spectrumCanvas.isVisible = true
                            targetCanvas.isVisible = true
                            doaResultLayout.isVisible = true
                        }

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
                        ctx.clearRect(0.0, 0.0, SPECTRUM_CANVAS_WIDTH.toDouble(), SPECTRUM_CANVAS_HEIGHT.toDouble())
                        ctx.beginPath()
                        ctx.setStrokeStyle("blue")
                        ctx.rect(1.0, 1.0, (SPECTRUM_CANVAS_WIDTH - 2).toDouble(), (SPECTRUM_CANVAS_HEIGHT - 2).toDouble())
                        ctx.setStrokeStyle("red")
                        for (i in shortSpectrum.indices) {
                            val x = i.toDouble() / shortSpectrum.size.toDouble() * SPECTRUM_CANVAS_WIDTH.toDouble()
                            val y = (1.0 - (shortSpectrum[i] + 100.0f).toDouble() / 80.0) * SPECTRUM_CANVAS_HEIGHT.toDouble()
                            if (i == 0) ctx.moveTo(x, y) else ctx.lineTo(x, y)
                        }
                        ctx.closePath()
                        ctx.stroke()
                        ctx.restore()
                    }
                }
            } catch (_: Exception) { }
        }
    }

    init {
        doaResultLayout.add(doaFreqTitle)
        doaResultLayout.add(doaFreqValue)
        doaResultLayout.add(doaDestLayout)
        doaResultLayout.add(classificationResultLayout)
        
        // Скрываем графики изначально
        doaResultLayout.isVisible = false
        targetCanvas.isVisible = false
        spectrumCanvas.isVisible = false

        settingsLayout.add(Span("Центральная частота кракена"))
        settingsLayout.add(daqFrequencyText)
        settingsLayout.add(Span("МГц"))
        settingsLayout.add(daqFrequencyApply)

        val calibrateButton = Button("Калибровать")
        calibrateButton.themeName = "secondary"
        calibrateButton.addClickListener {
            val value = daqFrequencyText.value?.toFloatOrNull()
            if (value == null || value <= 0f) {
                Notification.show("Сначала введите частоту", 3000, Notification.Position.TOP_CENTER)
                return@addClickListener
            }
            appState.daqFrequencyMhz = value
            Notification.show("Запущена калибровка... (ожидайте ~5 сек)", 3000, Notification.Position.TOP_CENTER)
            showLoading() // Показываем загрузку при калибровке
            Thread {
                try { krakenDecorator.setFrequency(value) } catch (_: Exception) {}
            }.start()
        }
        settingsLayout.add(calibrateButton)

        antennaSelect.label = "Конфигурация антенны"
        antennaSelect.setWidth("300px")
        antennaSelect.isEnabled = false
        antennaSelect.placeholder = "Загрузка..."

        daqFrequencyText.value = appState.daqFrequencyMhz.toString()

        add(doaResultLayout)
        add(targetCanvas)
        add(Span("Спектр"))
        add(spectrumCanvas)
        add(settingsLayout)
        add(antennaSelect)

        // Добавляем индикатор загрузки
        loadingLayout.add(loadingText, progressBar)
        add(loadingLayout)

        val musicSpectrumButton = Button("MUSIC-спектр")
        musicSpectrumButton.themeName = "secondary"
        musicSpectrumButton.addClickListener { UI.getCurrent().navigate("music-spectrum") }
        add(musicSpectrumButton)

        val mapButton = Button("Карта")
        mapButton.themeName = "secondary"
        mapButton.addClickListener { UI.getCurrent().navigate("map?area=voronezh") }
        add(mapButton)

        val pogonovoButton = Button("Полигон Погоново")
        pogonovoButton.themeName = "secondary"
        pogonovoButton.addClickListener { UI.getCurrent().navigate("map?area=pogonovo") }
        add(pogonovoButton)

        add(recordButton)
        add(stopButton)

        rebootButton.themeName = "error"
        rebootButton.addClickListener {
            ConfirmDialog().apply {
                setHeader("Перезагрузить все сервисы?")
                setText("Это перезапустит DAQ, бэкенд и веб-интерфейс с принудительной очисткой зависших процессов. Страница будет недоступна около 40 секунд.")
                setConfirmText("Перезагрузить")
                setCancelText("Отмена")
                setCancelable(true)

                addConfirmListener {
                    rebootService.restartAll()
                    Notification.show("Идет глубокая перезагрузка системы. Подождите 40 секунд...", 5000, Notification.Position.TOP_CENTER)
                    UI.getCurrent().page.executeJs("setTimeout(function(){ window.location.reload(); }, 40000);")
                }
                open()
            }
        }
        add(rebootButton)

        stopButton.themeName = "primary error"
        recordButton.themeName = "success"

        loadAntennaPresetsAsync()

        antennaSelect.addValueChangeListener { event ->
            val newKey = event.value ?: return@addValueChangeListener
            if (newKey == currentAntennaKey) return@addValueChangeListener

            val oldDisplay = event.oldValue ?: "—"
            ConfirmDialog().apply {
                setHeader("Сменить конфигурацию антенны?")
                setText("Вы переключаетесь с '$oldDisplay' на '${displayNameFor(newKey)}'.\n\nУбедитесь, что физически подключён именно этот блок антенн.")
                setConfirmText("Переключить")
                setCancelText("Отмена")
                setCancelable(true)

                addConfirmListener {
                    Thread {
                        val response = try { krakenDecorator.setAntennaPreset(newKey) } catch (e: Exception) { null }
                        val ui = attachedUi
                        try {
                            ui?.access {
                                if (response != null && response.success) {
                                    currentAntennaKey = response.current
                                    Notification.show("Антенна переключена: $newKey", 3000, Notification.Position.TOP_CENTER)
                                } else {
                                    Notification.show("Не удалось переключить антенну", 5000, Notification.Position.TOP_CENTER)
                                    antennaSelect.value = currentAntennaKey
                                }
                            }
                        } catch (_: Exception) { }
                    }.start()
                }
                addCancelListener { antennaSelect.value = currentAntennaKey }
                open()
            }
        }

        stopButton.addClickListener {
            ConfirmDialog().apply {
                setHeader("Остановить сервер?")
                setText("Бэкенд перестанет обрабатывать данные. Продолжить?")
                setConfirmText("Остановить")
                setCancelable(true)
                addConfirmListener {
                    Thread { try { krakenDecorator.stop() } catch (_: Exception) {} }.start()
                }
                open()
            }
        }

        recordButton.addClickListener {
            Thread {
                val wantToStart = !isRecording
                val response = try { krakenDecorator.setRecording(wantToStart) } catch (e: Exception) { null }
                val ui = attachedUi
                try {
                    ui?.access {
                        if (response == null) {
                            Notification.show("Ошибка записи", 5000, Notification.Position.TOP_CENTER)
                            return@access
                        }
                        isRecording = response.enabled
                        if (isRecording) {
                            recordButton.text = "Остановить запись"
                            recordButton.themeName = "error"
                            Notification.show("Запись начата: ${response.path}", 5000, Notification.Position.TOP_CENTER)
                        } else {
                            recordButton.text = "Начать запись"
                            recordButton.themeName = "success"
                            Notification.show("Запись остановлена. Сохранено ${response.framesWritten} кадров", 7000, Notification.Position.TOP_CENTER)
                        }
                    }
                } catch (_: Exception) { }
            }.start()
        }

        daqFrequencyApply.addClickListener {
            val value = daqFrequencyText.value?.toFloatOrNull()
            if (value == null || value <= 0f) {
                Notification.show("Введите корректную частоту в МГц", 3000, Notification.Position.TOP_CENTER)
                return@addClickListener
            }
            appState.daqFrequencyMhz = value
            showLoading() // Показываем загрузку при смене частоты
            Thread { try { krakenDecorator.setFrequency(value) } catch (_: Exception) {} }.start()
        }
    }

    // Метод для показа индикатора загрузки
    private fun showLoading() {
        loadingLayout.isVisible = true
        doaResultLayout.isVisible = false
        targetCanvas.isVisible = false
        spectrumCanvas.isVisible = false
    }

    private fun loadAntennaPresetsAsync() {
        Thread {
            val response = try { krakenDecorator.getAntennaPresets() } catch (e: Exception) { null }
            val ui = attachedUi
            try {
                ui?.access {
                    if (response != null && response.availableListList.isNotEmpty()) {
                        val keys = response.availableListList.map { it.key }
                        antennaSelect.setItems(keys as Collection<String>)
                        antennaSelect.setItemLabelGenerator { key -> response.availableListList.find { it.key == key }?.displayName ?: key }
                        currentAntennaKey = response.current
                        antennaSelect.value = response.current
                        antennaSelect.isEnabled = true
                        antennaSelect.placeholder = null
                    } else {
                        antennaSelect.isEnabled = false
                        antennaSelect.placeholder = "Пресеты недоступны"
                    }
                }
            } catch (_: Exception) { }
        }.start()
    }

    private fun displayNameFor(key: String): String {
        return try {
            val response = krakenDecorator.getAntennaPresets()
            response.availableListList.find { it.key == key }?.displayName ?: key
        } catch (e: Exception) { key }
    }
}