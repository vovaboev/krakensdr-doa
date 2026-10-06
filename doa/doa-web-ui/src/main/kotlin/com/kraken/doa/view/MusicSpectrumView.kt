package com.kraken.doa.view

import com.kraken.doa.grpc.KrakenDecorator
import com.karaken.MusicSpectrumData
import com.vaadin.flow.component.AttachEvent
import com.vaadin.flow.component.DetachEvent
import com.vaadin.flow.component.UI
import com.vaadin.flow.component.button.Button
import com.vaadin.flow.component.html.Div
import com.vaadin.flow.component.html.H2
import com.vaadin.flow.component.html.Image
import com.vaadin.flow.component.html.Span
import com.vaadin.flow.component.orderedlayout.HorizontalLayout
import com.vaadin.flow.component.orderedlayout.VerticalLayout
import com.vaadin.flow.router.Route
import org.vaadin.pekkam.Canvas
import java.awt.image.BufferedImage
import java.awt.image.DataBufferInt
import java.io.ByteArrayOutputStream
import java.util.Base64
import java.util.Locale
import javax.imageio.ImageIO

@Route("music-spectrum")
class MusicSpectrumView(private val krakenDecorator: KrakenDecorator) : VerticalLayout() {

    companion object {
        private const val IMG_W = 480
        private const val IMG_H = 240
        private const val LEGEND_W = 80
        private const val LEGEND_H = IMG_H

        private val PALETTE: IntArray = buildPalette()

        private fun buildPalette(): IntArray {
            val palette = IntArray(256)
            for (i in 0..255) {
                val t = i / 255.0
                val r = channelRed(t)
                val g = channelGreen(t)
                val b = channelBlue(t)
                palette[i] = (r shl 16) or (g shl 8) or b
            }
            return palette
        }

        private fun channelRed(t: Double): Int = when {
            t < 0.30 -> 0
            t < 0.60 -> ((t - 0.30) / 0.30 * 200).toInt()
            t < 0.80 -> 200 + ((t - 0.60) / 0.20 * 55).toInt()
            else -> 255
        }

        private fun channelGreen(t: Double): Int = when {
            t < 0.20 -> 0
            t < 0.50 -> ((t - 0.20) / 0.30 * 255).toInt()
            t < 0.80 -> 255
            else -> (255 - (t - 0.80) / 0.20 * 255).toInt().coerceAtLeast(0)
        }

        private fun channelBlue(t: Double): Int = when {
            t < 0.15 -> 128 + ((t / 0.15) * 127).toInt()
            t < 0.45 -> (255 - (t - 0.15) / 0.30 * 255).toInt()
            t < 0.65 -> ((t - 0.45) / 0.20 * 100).toInt()
            else -> 100
        }
    }

    private val img = Image()
    private val clickCanvas = Canvas(IMG_W, IMG_H)
    private val legendCanvas = Canvas(LEGEND_W, LEGEND_H)
    private val statusLabel = Span("Ожидание данных...")
    private val toggleButton = Button("Выключить")

    private var attachedUi: UI? = null
    private var isEnabled = true
    private var lastData: MusicSpectrumData? = null

    override fun onAttach(attachEvent: AttachEvent?) {
        attachedUi = attachEvent?.ui
        if (isEnabled) {
            subscribe()
        }
    }

    override fun onDetach(detachEvent: DetachEvent?) {
        krakenDecorator.cancelSubscriptionMusicSpectrum()
        attachedUi = null
    }

    init {
        add(H2("MUSIC-спектр"))

        val container = Div()
        container.style.set("position", "relative")
        container.style.set("width", "${IMG_W}px")
        container.style.set("height", "${IMG_H}px")
        container.style.set("border", "1px solid #ccc")
        container.style.set("flex-shrink", "0")

        img.width = "${IMG_W}px"
        img.height = "${IMG_H}px"
        img.style.set("position", "absolute")
        img.style.set("top", "0")
        img.style.set("left", "0")
        img.style.set("z-index", "1")
        img.style.set("pointer-events", "none")
        img.style.set("image-rendering", "pixelated")

        clickCanvas.style.set("position", "absolute")
        clickCanvas.style.set("top", "0")
        clickCanvas.style.set("left", "0")
        clickCanvas.style.set("z-index", "2")

        container.add(img, clickCanvas)

        val hLayout = HorizontalLayout()
        hLayout.add(container)
        hLayout.add(legendCanvas)

        add(hLayout)
        add(statusLabel)
        add(toggleButton)

        toggleButton.addClickListener {
            isEnabled = !isEnabled
            if (isEnabled) {
                toggleButton.text = "Выключить"
                subscribe()
            } else {
                toggleButton.text = "Включить"
                krakenDecorator.cancelSubscriptionMusicSpectrum()
                statusLabel.text = "Отключено"
            }
        }

        clickCanvas.addMouseDownListener { ev ->
            val x = ev.offsetX.toInt()
            val y = ev.offsetY.toInt()
            val data = lastData
            if (data == null || x < 0 || x >= IMG_W || y < 0 || y >= IMG_H) {
                return@addMouseDownListener
            }

            val az = data.azMin + x.toFloat() / IMG_W * (data.azMax - data.azMin)
            val el = data.elMax - y.toFloat() / IMG_H * (data.elMax - data.elMin)

            val azIdx = (x.toFloat() / IMG_W * data.nAz).toInt().coerceIn(0, data.nAz - 1)
            val elIdx = (y.toFloat() / IMG_H * data.nEl).toInt().coerceIn(0, data.nEl - 1)
            val index = elIdx * data.nAz + azIdx
            val level = if (index < data.levels.size()) {
                data.levels.byteAt(index).toInt() and 0xFF
            } else 0

            val percent = (level * 100) / 255
            statusLabel.text = String.format(
                Locale.US,
                "Азимут: %.1f° | Угол места: %.1f° | Уровень: %d%% (raw: %d)",
                az, el, percent, level
            )
        }

        drawLegend()
    }

    private fun subscribe() {
        krakenDecorator.subscribeToMusicSpectrum { data ->
            attachedUi?.access {
                lastData = data
                val png = renderHeatmap(data)
                if (png != null) {
                    val b64 = Base64.getEncoder().encodeToString(png)
                    img.element.setAttribute("src", "data:image/png;base64,$b64")
                    statusLabel.text = String.format(
                        Locale.US,
                        "Частота: %.3f МГц | %d×%d | кликните по карте",
                        data.freq / 1e6, data.nAz, data.nEl
                    )
                }
            }
        }
    }

    private fun drawLegend() {
        val ctx = legendCanvas.context
        val barX = 5.0
        val barW = 28.0
        val barH = IMG_H - 20.0
        val top = 10.0

        for (i in 0..255) {
            val t = i / 255.0
            val y = top + barH * (1.0 - t)
            val color = PALETTE[i]
            val r = (color shr 16) and 0xFF
            val g = (color shr 8) and 0xFF
            val b = color and 0xFF
            ctx.setFillStyle("rgb($r,$g,$b)")
            ctx.fillRect(barX, y, barW, 1.0)
        }

        ctx.setStrokeStyle("black")
        ctx.setLineWidth(1.0)
        ctx.strokeRect(barX, top, barW, barH)

        ctx.setFillStyle("black")
        ctx.setFont("11px sans-serif")

        ctx.fillText("0 dB", barX + barW + 6.0, top + 10.0)
        ctx.fillText("−10", barX + barW + 6.0, top + barH * 0.33)
        ctx.fillText("−20", barX + barW + 6.0, top + barH * 0.67)
        ctx.fillText("−30", barX + barW + 6.0, top + barH - 2.0)

        ctx.setFont("10px sans-serif")
        ctx.fillText("уровень, дБ", 3.0, 8.0)
    }

    private fun renderHeatmap(data: MusicSpectrumData): ByteArray? {
        return try {
            val nAz = data.nAz
            val nEl = data.nEl
            if (nAz <= 0 || nEl <= 0) return null

            val levels = data.levels.toByteArray()
            if (levels.size < nAz * nEl) return null

            val image = BufferedImage(IMG_W, IMG_H, BufferedImage.TYPE_INT_RGB)
            val pixels = (image.raster.dataBuffer as DataBufferInt).data

            val azIdx = IntArray(IMG_W) { px ->
                (px.toDouble() / IMG_W * nAz).toInt().coerceIn(0, nAz - 1)
            }

            var outIdx = 0
            for (py in 0 until IMG_H) {
                val elIdx = (py.toDouble() / IMG_H * nEl).toInt().coerceIn(0, nEl - 1)
                val rowBase = elIdx * nAz
                for (px in 0 until IMG_W) {
                    val idx = rowBase + azIdx[px]
                    val level = (levels[idx].toInt() and 0xFF).coerceIn(0, 255)
                    pixels[outIdx++] = PALETTE[level]
                }
            }

            val baos = ByteArrayOutputStream()
            ImageIO.write(image, "png", baos)
            baos.toByteArray()
        } catch (e: Exception) {
            null
        }
    }
}