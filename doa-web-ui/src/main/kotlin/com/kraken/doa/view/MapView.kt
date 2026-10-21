package com.kraken.doa.view

import com.kraken.doa.grpc.KrakenDecorator
import com.kraken.doa.service.AppStateService
import com.vaadin.flow.component.AttachEvent
import com.vaadin.flow.component.ClientCallable
import com.vaadin.flow.component.DetachEvent
import com.vaadin.flow.component.UI
import com.vaadin.flow.component.button.Button
import com.vaadin.flow.component.html.Div
import com.vaadin.flow.component.html.Span
import com.vaadin.flow.component.notification.Notification
import com.vaadin.flow.component.orderedlayout.HorizontalLayout
import com.vaadin.flow.component.orderedlayout.VerticalLayout
import com.vaadin.flow.component.textfield.TextField
import com.vaadin.flow.router.Route
import kotlin.math.*

@Route("map")
class MapView(
    private val krakenDecorator: KrakenDecorator,
    private val appState: AppStateService
) : VerticalLayout() {

    private val coneLengthMeters = 5000.0
    private val coneHalfAngleDeg = 10.0

    private val mapDiv = Div()
    private val freqField = TextField("Центральная частота, МГц")
    private val freqApply = Button("Применить")
    private val latField = TextField("Широта")
    private val lonField = TextField("Долгота")
    private val coordsApply = Button("Применить")
    
    private val pointsInfoLayout = VerticalLayout()
    private val clearPinsButton = Button("Очистить метки")
    private val statusLabel = Span("Ожидание данных MUSIC...")

    private var attachedUi: UI? = null
    private var currentElevation = 0.0

    override fun onAttach(attachEvent: AttachEvent?) {
        attachedUi = attachEvent?.ui
        val page = attachedUi?.page
        page?.addStyleSheet("/ol/ol.css")
        page?.addJavaScript("/ol/ol.js")
        initMapInBrowser()
        subscribeToDoa()
    }

    override fun onDetach(detachEvent: DetachEvent?) {
        try { krakenDecorator.cancelSubscriptionToDaoResult() } catch (_: Exception) {}
        attachedUi = null
    }

    init {
        setSizeFull()
        mapDiv.setWidth("100%")
        mapDiv.setHeight("500px")
        mapDiv.element.setAttribute("id", "kraken-map")

        freqField.value = appState.daqFrequencyMhz.toString()
        freqField.setWidth("150px")
        val freqRow = HorizontalLayout(freqField, freqApply)
        freqApply.addClickListener {
            val value = freqField.value?.toFloatOrNull()
            if (value == null || value <= 0f) {
                Notification.show("Введите корректную частоту в МГц")
                return@addClickListener
            }
            appState.daqFrequencyMhz = value
            Thread {
                try { krakenDecorator.setFrequency(value) } catch (_: Exception) {}
            }.start()
            Notification.show("Частота: $value МГц", 2000, Notification.Position.TOP_CENTER)
        }

        latField.value = appState.antennaLat.toString()
        lonField.value = appState.antennaLon.toString()
        latField.setWidth("150px")
        lonField.setWidth("150px")
        val coordsRow = HorizontalLayout(latField, lonField, coordsApply)
        coordsApply.addClickListener {
            val newLat = latField.value?.toDoubleOrNull()
            val newLon = lonField.value?.toDoubleOrNull()
            if (newLat == null || newLon == null) {
                Notification.show("Введите корректные координаты")
                return@addClickListener
            }
            appState.antennaLat = newLat
            appState.antennaLon = newLon
            attachedUi?.access {
                mapDiv.element.executeJs(
                    "window.krakenMap && window.krakenMap.getView().setCenter(ol.proj.fromLonLat([$newLon, $newLat]));" +
                    "window.krakenMarker && window.krakenMarker.getGeometry().setCoordinates(ol.proj.fromLonLat([$newLon, $newLat]));"
                )
                clearPins()
            }
        }

        clearPinsButton.addClickListener {
            clearPins()
        }

        pointsInfoLayout.style.set("margin-top", "10px")

        add(freqRow)
        add(coordsRow)
        add(HorizontalLayout(clearPinsButton))
        add(mapDiv)
        add(pointsInfoLayout)
        add(statusLabel)
    }

    private fun clearPins() {
        pointsInfoLayout.removeAll()
        attachedUi?.access {
            mapDiv.element.executeJs(
                """
                (function() {
                    if (window.krakenClickLayer) {
                        window.krakenClickLayer.getSource().clear();
                    }
                    window.krakenPointCounter = 0;
                })();
                """.trimIndent()
            )
        }
    }

    @ClientCallable
    fun onMapClick(pointIndex: Int, distance: Double, azimuth: Double) {
        val elText = if (currentElevation != -999.0) "%.1f°".format(currentElevation) else "Нет сигнала"
        val infoText = "Точка $pointIndex: До цели: %.0f м | Азимут: %.1f° | Угол места (MUSIC): $elText".format(distance, azimuth)
        
        val infoSpan = Span(infoText)
        pointsInfoLayout.add(infoSpan)
    }

    private fun initMapInBrowser() {
        attachedUi?.access {
            mapDiv.element.executeJs(
                """
                (function tryInit(serverElement) {
                    if (typeof ol === 'undefined') {
                        setTimeout(function() { tryInit(serverElement); }, 100);
                        return;
                    }
                    var el = document.getElementById('kraken-map');
                    if (!el) {
                        setTimeout(function() { tryInit(serverElement); }, 100);
                        return;
                    }
                    if (window.krakenMap) {
                        try { window.krakenMap.setTarget(null); } catch(e) {}
                        window.krakenMap = null;
                    }
                    
                    window.krakenPointCounter = 0;
                    
                    window.krakenMap = new ol.Map({
                        target: 'kraken-map',
                        layers: [
                            new ol.layer.Tile({
                                source: new ol.source.XYZ({
                                    url: '/tiles/{z}/{x}/{y}.png'
                                })
                            })
                        ],
                        view: new ol.View({
                            center: ol.proj.fromLonLat([${appState.antennaLon}, ${appState.antennaLat}]),
                            zoom: 12,
                            minZoom: 10,
                            maxZoom: 14
                        })
                    });
                    
                    window.krakenMarker = new ol.Feature({
                        geometry: new ol.geom.Point(ol.proj.fromLonLat([${appState.antennaLon}, ${appState.antennaLat}]))
                    });
                    var vectorSource = new ol.source.Vector({ features: [window.krakenMarker] });
                    window.krakenVectorLayer = new ol.layer.Vector({ source: vectorSource });
                    window.krakenMap.addLayer(window.krakenVectorLayer);
                    
                    window.krakenClickLayer = new ol.layer.Vector({ source: new ol.source.Vector() });
                    window.krakenMap.addLayer(window.krakenClickLayer);
                    
                    window.krakenCone = null;
                    
                    window.krakenMap.on('click', function(evt) {
                        window.krakenPointCounter++;
                        var currentIdx = window.krakenPointCounter;
                        
                        var lonLat = ol.proj.toLonLat(evt.coordinate);
                        var clickLon = lonLat[0];
                        var clickLat = lonLat[1];
                        var cLon = ${appState.antennaLon};
                        var cLat = ${appState.antennaLat};

                        var R = 6371000;
                        var dLat = (clickLat - cLat) * Math.PI / 180;
                        var dLon = (clickLon - cLon) * Math.PI / 180;
                        var a = Math.sin(dLat/2) * Math.sin(dLat/2) +
                                Math.cos(cLat * Math.PI / 180) * Math.cos(clickLat * Math.PI / 180) *
                                Math.sin(dLon/2) * Math.sin(dLon/2);
                        var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
                        var dist = R * c;

                        var y = Math.sin(dLon) * Math.cos(clickLat * Math.PI / 180);
                        var x = Math.cos(cLat * Math.PI / 180) * Math.sin(clickLat * Math.PI / 180) -
                                Math.sin(cLat * Math.PI / 180) * Math.cos(clickLat * Math.PI / 180) * Math.cos(dLon);
                        var brng = Math.atan2(y, x) * 180 / Math.PI;
                        brng = (brng + 360) % 360;

                        var line = new ol.Feature({
                            geometry: new ol.geom.LineString([
                                ol.proj.fromLonLat([cLon, cLat]),
                                evt.coordinate
                            ])
                        });
                        line.setStyle(new ol.style.Style({
                            stroke: new ol.style.Stroke({ color: 'blue', width: 2, lineDash: [5, 5] })
                        }));

                        var pt = new ol.Feature({
                            geometry: new ol.geom.Point(evt.coordinate)
                        });
                        pt.setStyle(new ol.style.Style({
                            image: new ol.style.Circle({
                                radius: 6,
                                fill: new ol.style.Fill({color: 'blue'}),
                                stroke: new ol.style.Stroke({color: 'white', width: 1})
                            }),
                            text: new ol.style.Text({
                                text: currentIdx.toString(),
                                offsetY: -15,
                                font: 'bold 14px sans-serif',
                                fill: new ol.style.Fill({color: 'black'}),
                                stroke: new ol.style.Stroke({color: 'white', width: 3})
                            })
                        }));

                        window.krakenClickLayer.getSource().addFeature(line);
                        window.krakenClickLayer.getSource().addFeature(pt);

                        if (serverElement && serverElement.${'$'}server && serverElement.${'$'}server.onMapClick) {
                            serverElement.${'$'}server.onMapClick(currentIdx, dist, brng);
                        }
                    });

                    console.log('Kraken map initialized with numbered points');
                })(${'$'}0);
                """.trimIndent(),
                getElement()
            )
        }
    }

    private fun subscribeToDoa() {
        krakenDecorator.subscribeToDaoResult { result ->
            val ui = attachedUi ?: return@subscribeToDaoResult
            try {
                ui.access {
                    if (result.res.destinationsList.isEmpty()) {
                        clearCone("Нет данных")
                        currentElevation = -999.0
                        return@access
                    }
                    val first = result.res.destinationsList[0]
                    val noSignal = (first.a == -909.0f) && (first.b == -999.0f)
                    if (noSignal) {
                        clearCone("Сигнал не обнаружен")
                        currentElevation = -999.0
                        return@access
                    }
                    val azimuthDeg = first.a - 90.0
                    val elevationDeg = first.b
                    
                    currentElevation = elevationDeg.toDouble()
                    
                    statusLabel.text = "Азимут (MUSIC): %.1f° | Угол места (MUSIC): %.1f°".format(azimuthDeg, elevationDeg)
                    drawCone(azimuthDeg.toDouble())
                }
            } catch (_: Exception) { }
        }
    }

    private fun clearCone(message: String) {
        statusLabel.text = message
        attachedUi?.access {
            mapDiv.element.executeJs(
                """
                (function() {
                    if (window.krakenVectorLayer && window.krakenCone) {
                        window.krakenVectorLayer.getSource().removeFeature(window.krakenCone);
                        window.krakenCone = null;
                    }
                })();
                """.trimIndent()
            )
        }
    }

    private fun drawCone(azimuthDeg: Double) {
        val bearingLeft = Math.toRadians(azimuthDeg - coneHalfAngleDeg)
        val bearingRight = Math.toRadians(azimuthDeg + coneHalfAngleDeg)
        val (leftLat, leftLon) = destinationPoint(appState.antennaLat, appState.antennaLon, bearingLeft, coneLengthMeters)
        val (rightLat, rightLon) = destinationPoint(appState.antennaLat, appState.antennaLon, bearingRight, coneLengthMeters)

        attachedUi?.access {
            mapDiv.element.executeJs(
                """
                (function() {
                    if (!window.krakenMap || !window.krakenVectorLayer) return;
                    if (window.krakenCone) {
                        window.krakenVectorLayer.getSource().removeFeature(window.krakenCone);
                    }
                    var points = [
                        ol.proj.fromLonLat([${appState.antennaLon}, ${appState.antennaLat}]),
                        ol.proj.fromLonLat([$leftLon, $leftLat]),
                        ol.proj.fromLonLat([$rightLon, $rightLat]),
                        ol.proj.fromLonLat([${appState.antennaLon}, ${appState.antennaLat}])
                    ];
                    window.krakenCone = new ol.Feature({
                        geometry: new ol.geom.Polygon([points])
                    });
                    window.krakenCone.setStyle(new ol.style.Style({
                        fill: new ol.style.Fill({ color: 'rgba(255, 0, 0, 0.35)' }),
                        stroke: new ol.style.Stroke({ color: 'red', width: 2 })
                    }));
                    window.krakenVectorLayer.getSource().addFeature(window.krakenCone);
                })();
                """.trimIndent()
            )
        }
    }

    private fun destinationPoint(
        latDeg: Double, lonDeg: Double,
        bearingRad: Double, distanceMeters: Double
    ): Pair<Double, Double> {
        val R = 6371000.0
        val lat1 = Math.toRadians(latDeg)
        val lon1 = Math.toRadians(lonDeg)
        val d = distanceMeters / R
        val lat2 = asin(sin(lat1) * cos(d) + cos(lat1) * sin(d) * cos(bearingRad))
        val lon2 = lon1 + atan2(
            sin(bearingRad) * sin(d) * cos(lat1),
            cos(d) - sin(lat1) * sin(lat2)
        )
        return Pair(Math.toDegrees(lat2), Math.toDegrees(lon2))
    }
}