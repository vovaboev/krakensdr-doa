package com.kraken.doa.view

import com.kraken.doa.grpc.KrakenDecorator
import com.vaadin.flow.component.AttachEvent
import com.vaadin.flow.component.DetachEvent
import com.vaadin.flow.component.UI
import com.vaadin.flow.component.button.Button
import com.vaadin.flow.component.dialog.Dialog
import com.vaadin.flow.component.html.Span
import com.vaadin.flow.component.notification.Notification
import com.vaadin.flow.component.orderedlayout.HorizontalLayout
import com.vaadin.flow.component.orderedlayout.VerticalLayout
import com.vaadin.flow.component.textfield.TextField
import com.vaadin.flow.router.Route
import org.vaadin.pekkam.Canvas

@Route("/spectrum")
class SpectrumView(private val krakenDecorator: KrakenDecorator) : VerticalLayout() {

    companion object {
        private const val SPECTRUM_CANVAS_WIDTH = 800
        private const val SPECTRUM_CANVAS_HEIGHT = 300
        private const val ONE_POS_RESOL = 32
        private const val DEFAULT_LEFT_MHZ = 650.0f
        private const val DEFAULT_RIGHT_MHZ = 1700.0f
        private const val STEP_MHZ = 2.0f
    }

    private var attachedUi: UI? = null

    private val leftFreq = TextField("Левая граница (МГц)")
    private val rightFreq = TextField("Правая граница (МГц)")
    private val apply = Button("Применить")

    private var leftFreqVal = DEFAULT_LEFT_MHZ
    private var rightFreqVal = DEFAULT_RIGHT_MHZ

    private val freqList = ArrayList<Float>()
    private var amps = FloatArray(0)

    private val spectrumCanvas = Canvas(SPECTRUM_CANVAS_WIDTH, SPECTRUM_CANVAS_HEIGHT)

    override fun onAttach(attachEvent: AttachEvent?) {
        attachedUi = attachEvent?.ui
    }

    override fun onDetach(detachEvent: DetachEvent?) {
        krakenDecorator.cancelSubscriptionSpectrum()
        attachedUi = null
    }

    init {
        val hor = HorizontalLayout()
        hor.add(leftFreq)
        hor.add(rightFreq)
        hor.add(apply)

        add(hor)
        add(spectrumCanvas)

        leftFreq.value = leftFreqVal.toString()
        rightFreq.value = rightFreqVal.toString()

        freqIntervalApply(leftFreqVal, rightFreqVal)

        apply.addClickListener {
            val left = leftFreq.value?.toFloatOrNull()
            val right = rightFreq.value?.toFloatOrNull()
            if (left == null || right == null || left >= right) {
                Notification.show("Левая граница должна быть меньше правой")
                return@addClickListener
            }
            leftFreqVal = left
            rightFreqVal = right
            freqIntervalApply(left, right)
        }

        spectrumCanvas.addMouseDownListener { ev ->
            val clickFreq = ev.offsetX.toFloat() / SPECTRUM_CANVAS_WIDTH.toFloat() *
                    (rightFreqVal - leftFreqVal) + leftFreqVal

            val popupContent = VerticalLayout()
            popupContent.add(Span("Selected frequency: $clickFreq MHz"))
            val dialog = Dialog()
            dialog.add(popupContent)
            dialog.open()
        }

        krakenDecorator.subscribeToSpectrum { spectrum ->
            attachedUi?.access {
                if (spectrum.specList.isNotEmpty()) {
                    val freqIndex = indexOfFreq(spectrum.freq / 1.0e6f)
                    val nextFreqIndex = if (freqIndex + 1 >= freqList.size) 0 else freqIndex + 1
                    if (freqList.isNotEmpty()) {
                        krakenDecorator.setFrequency(freqList[nextFreqIndex])
                    }

                    val specListSize = spectrum.specList.size.toDouble()
                    val shortSpectrum = FloatArray(ONE_POS_RESOL) { -1000.0f }
                    for (i in 0 until spectrum.specList.size) {
                        val x = ((i.toDouble() / specListSize) * shortSpectrum.size.toDouble()).toInt()
                        if (shortSpectrum[x] < spectrum.specList[i]) {
                            shortSpectrum[x] = spectrum.specList[i]
                        }
                    }

                    if (freqIndex >= 0 && freqIndex < freqList.size) {
                        for (i in freqIndex * ONE_POS_RESOL until (freqIndex + 1) * ONE_POS_RESOL) {
                            amps[i] = shortSpectrum[i - freqIndex * ONE_POS_RESOL]
                        }

                        val drawSpectrum = FloatArray(SPECTRUM_CANVAS_WIDTH) { -1000.0f }
                        for (i in amps.indices) {
                            val x = ((i.toDouble() / amps.size) * drawSpectrum.size.toDouble()).toInt()
                            if (drawSpectrum[x] < amps[i]) {
                                drawSpectrum[x] = amps[i]
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
                        for (i in drawSpectrum.indices) {
                            val x = i.toDouble() / drawSpectrum.size.toDouble() * SPECTRUM_CANVAS_WIDTH.toDouble()
                            val y = (1.0 - (drawSpectrum[i] + 100.0f).toDouble() / 80.0) *
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
    }

    private fun freqIntervalApply(left: Float, right: Float) {
        if (left < right) {
            freqList.clear()
            var current = left + 1.0f
            while (current < right - 1.0f) {
                freqList.add(current)
                current += STEP_MHZ
            }
            amps = FloatArray(freqList.size * ONE_POS_RESOL)
            if (freqList.isNotEmpty()) {
                krakenDecorator.setFrequency(freqList[0])
            }
        }
    }

    private fun indexOfFreq(f: Float): Int =
        freqList.indexOfFirst { i -> (i - 0.001f) <= f && f <= (i + 0.001f) }
}