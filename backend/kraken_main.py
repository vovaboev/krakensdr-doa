import kraken_iqheader_patch  # только импорт, он сам всё навесит

from receiver.iq_header import IQHeader
from receiver.kraken_sdr_receiver import ReceiverRTLSDR
from queue import Queue, Empty, Full
import time

from scipy import fft, signal
import numpy as np
from doa_2d_music import MUSIC2D, SensorArray
from classify_signal import classify_signal
from threading import Thread, Event, Lock

from concurrent import futures
import logging

import os
import json
from datetime import datetime

import grpc
import kraken_pb2
import kraken_pb2_grpc


# ------------------------- Настройка логирования -------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(threadName)s: %(message)s",
)
logger = logging.getLogger(__name__)


# --------------------------- Глобальные объекты -------------------------

data_que = Queue(maxsize=5)
receiver = ReceiverRTLSDR(data_que, "eth", "127.0.0.1")
end_receiver_worker_event = Event()
end_receiver_worker_event.clear()

doa_result_queue = Queue()
doa_input_queue = Queue(maxsize=5)
spectrum_input_queue = Queue(maxsize=5)
spectrum_output_queue = Queue(maxsize=5)

classification_input_queue = Queue(maxsize=3)
classification_output_queue = Queue(maxsize=3)
music_spectrum_queue = Queue(maxsize=2)

# Порог нормализации MUSIC-спектра (дБ). Меняется через UI.
music_threshold_db = 2.5

receiver_lock = Lock()
prev_sync_ok = None


# ---------------------- Запись IQ-сигнала на диск ------------------------

RECORDINGS_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings")
os.makedirs(RECORDINGS_ROOT, exist_ok=True)


class RecordingState:
    """Состояние записи IQ-сигнала (потокобезопасное)."""

    def __init__(self):
        self.enabled = False
        self.directory = None
        self.frame_counter = 0
        self.sampling_freq = 0
        self.center_freq = 0
        self.lock = Lock()

    def start(self, folder_name: str = "") -> str:
        with self.lock:
            if self.enabled:
                return self.directory
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            name = folder_name.strip() or f"rec_{ts}"
            name = os.path.basename(name)
            path = os.path.join(RECORDINGS_ROOT, name)
            os.makedirs(path, exist_ok=True)
            self.directory = path
            self.frame_counter = 0
            self.enabled = True
            logger.info("Recording STARTED: %s", path)
            return path

    def stop(self) -> str:
        with self.lock:
            if not self.enabled:
                return ""
            meta = {
                "frames": self.frame_counter,
                "sampling_freq": self.sampling_freq,
                "center_freq": self.center_freq,
                "timestamp_stop": datetime.now().isoformat(),
            }
            try:
                with open(os.path.join(self.directory, "metadata.json"), "w") as f:
                    json.dump(meta, f, indent=2)
            except Exception:
                logger.exception("Failed to write metadata")
            logger.info(
                "Recording STOPPED: %d frames in %s",
                self.frame_counter,
                self.directory,
            )
            self.enabled = False
            return self.directory

    def save_frame(self, iq_samples: np.ndarray) -> None:
        """Сохраняет один кадр IQ (вызывается из receiver_loop)."""
        if not self.enabled:
            return
        with self.lock:
            if not self.enabled:
                return
            try:
                path = os.path.join(
                    self.directory, f"frame_{self.frame_counter:06d}.npy"
                )
                np.save(path, iq_samples)
                self.frame_counter += 1
            except Exception:
                logger.exception("Failed to save recording frame")


recording_state = RecordingState()


# ======================= ПРЕСЕТЫ АНТЕННЫХ БЛОКОВ =========================

ANTENNA_PRESETS = {
    "cross_mills_1": {
        "name": "Блок 1 — Крест Миллса",
        "x": np.array([0, 0, 0, 0, 0]),
        "y": np.array([0, 0.075, 0.3, 0.9, 1.9]),
        "z": np.array([0.1, -0.1, 0, 0, 0]),
    },
    "l_block_2": {
        "name": "Блок 2 — L-образная, 37 см",
        "x": np.array([ 0,     0,  0,     -0.005,   0]),
        "y": np.array([-0.24,  0,  0.145,  0,       0]),
        "z": np.array([ 0,     0,  0,      0.235,   0.37]),
    },
    # «Стрела» D1 — 5 лучей, 45 см, все элементы вертикальны (Z=0).
    # Координаты из размерной схемы: N/W в см → (x_восток, y_север) в метрах.
    "arrow_d1": {
        "name": "Блок 3 — «Стрела» D1 (5 лучей, 45 см)",
        "x": np.array([ 0.00,  0.45,  0.20, -0.20, -0.45]),
        "y": np.array([ 0.22, -0.10, -0.23, -0.23, -0.10]),
        "z": np.array([ 0.0,   0.0,   0.0,   0.0,   0.0 ]),
    },
}

current_preset_key = "l_block_2"   # стартовый пресет


def build_sensor_array(preset_key: str) -> SensorArray:
    p = ANTENNA_PRESETS[preset_key]
    element_positions = np.vstack([p["x"], p["y"], p["z"]])
    logger.info("SensorArray: пресет '%s' (%s)", preset_key, p["name"])
    return SensorArray(element_positions)


sensor_array = build_sensor_array(current_preset_key)

num_signals = 1

azimuth_scan = np.linspace(0, 180, 181)
elevation_scan = np.linspace(-10, 10, 21)

CALIBRATION_MODE = False


# ------------------------ Параметры обработки сигналов ------------------

target_fs_network = 40e4
target_fs_music = 2.4e6
n_samp = 1024 * 300
n_samp_net = 1024 * 1


# ---------------------- Модель классификации сигналов -------------------

CLASSIFICATION_ENABLED = False

onnx_model_path = "signalClassificationModel_quantized_V1.onnx"

class_labels = [
    "2G", "5G", "AM_Radio", "Bluetooth", "DECT",
    "DVB_T2", "EDGE", "FM_Radio", "GPS", "GSM",
    "LTE", "LoRa", "NB_IoT", "Satellite_Communication",
    "TETRA", "WiMax", "Wi_Fi", "ZigBee",
]

if CLASSIFICATION_ENABLED:
    signal_classifier = classify_signal(onnx_model_path, class_labels)
else:
    signal_classifier = None
    logger.info("Classification DISABLED")


# --------------------- Кеш объектов MUSIC для разных частот -------------

music_estimators = {}


def get_music_estimator(fc: float) -> MUSIC2D:
    key = float(fc)
    if key not in music_estimators:
        logger.info("Create MUSIC2D estimator for fc = %.0f Hz", fc)
        music_estimators[key] = MUSIC2D(
            sensor_array,
            fc,
            azimuth_scan,
            elevation_scan,
            num_signals,
        )
    return music_estimators[key]


def set_antenna_preset(preset_key: str) -> bool:
    """Меняет активный пресет антенны и чистит кэш MUSIC-оценщиков."""
    global sensor_array, current_preset_key

    if preset_key not in ANTENNA_PRESETS:
        logger.warning("Неизвестный пресет антенны: %s", preset_key)
        return False

    if preset_key == current_preset_key:
        return True

    current_preset_key = preset_key
    sensor_array = build_sensor_array(preset_key)

    # steering-векторы зависят от геометрии — старый кэш невалиден
    music_estimators.clear()
    logger.info("Кэш MUSIC-оценщиков очищен (смена антенны)")

    return True


# ----------------------------- Потоки обработки -------------------------


def receiver_loop():
    logger.info("Receiver loop started")
    global prev_sync_ok

    try:
        while not end_receiver_worker_event.is_set():
            with receiver_lock:
                get_iq_failed = receiver.get_iq_online()
                iq_header: IQHeader = receiver.iq_header
                iq_samples = receiver.iq_samples
                sampling_freq = iq_header.sampling_freq if iq_header else None
                fc = receiver.daq_center_freq

            if iq_header is None:
                logger.warning("Receiver: no IQ header")
                time.sleep(0.01)
                continue

            cur_sync_ok = iq_header.sync_ok
            iq_header.log_sync_status(logger)

            if prev_sync_ok is None:
                prev_sync_ok = cur_sync_ok
            elif cur_sync_ok != prev_sync_ok:
                logger.warning(
                    "SYNC STATE CHANGED: frame=%d %s -> %s",
                    iq_header.cpi_index, prev_sync_ok, cur_sync_ok,
                )
                prev_sync_ok = cur_sync_ok

            if get_iq_failed:
                time.sleep(0.01)
                continue

            if not isinstance(iq_samples, np.ndarray):
                time.sleep(0.01)
                continue

            if iq_samples.size == 0:
                time.sleep(0.01)
                continue

            if not iq_header.is_valid:
                logger.warning("Receiver: invalid sync_word, frame=%d", iq_header.cpi_index)
                continue

            if not iq_header.is_data_frame:
                time.sleep(0.01)
                continue

            processed_signal = np.ascontiguousarray(iq_samples)

            # ---------- Запись IQ-кадра ----------
            if recording_state.enabled:
                if recording_state.frame_counter == 0:
                    with recording_state.lock:
                        recording_state.sampling_freq = int(sampling_freq or 0)
                        recording_state.center_freq = int(fc or 0)
                recording_state.save_frame(processed_signal)

            # ---------- DOA / MUSIC ----------
            if iq_header.can_use_for_music:
                try:
                    complex_data = processed_signal[:5, :n_samp]
                except Exception:
                    logger.exception("Unexpected IQ data shape: %s", processed_signal.shape)
                    complex_data = None

                if complex_data is not None:
                    if CALIBRATION_MODE:
                        calib_len = min(20000, complex_data.shape[1])
                        calib_chunk = complex_data[:, :calib_len]
                        calib_logger = logging.getLogger("Calib")
                        sensor_array.debug_channel_powers(
                            calib_chunk, logger=calib_logger, normalize=True,
                        )

                    signal_sCA = complex_data
                    if signal_sCA is not None:
                        doa_input_entity = {"signal": signal_sCA, "freq": fc}
                        try:
                            doa_input_queue.put_nowait(doa_input_entity)
                        except Full:
                            logger.debug("DOA input queue is full")

            # ---------- Спектр ----------
            try:
                single_ch = processed_signal[1, :]
            except Exception:
                logger.exception("Error extracting single channel")
                continue

            spectrum_input_entity = {
                "sampling_rate": sampling_freq,
                "signal": single_ch,
                "central_freq": fc,
            }
            try:
                spectrum_input_queue.put_nowait(spectrum_input_entity)
            except Full:
                logger.debug("Spectrum input queue is full")

            # ---------- Классификация ----------
            if CLASSIFICATION_ENABLED:
                classification_input_entity = {
                    "signal": processed_signal[:, :n_samp_net],
                    "sampling_rate": sampling_freq,
                }
                try:
                    classification_input_queue.put_nowait(classification_input_entity)
                except Full:
                    logger.debug("Classification input queue is full")

    except Exception:
        logger.exception("Fatal error in receiver_loop")
        end_receiver_worker_event.set()
    finally:
        logger.info("Receiver loop stopped")


def music_loop():
    logger.info("MUSIC loop started")
    try:
        while not end_receiver_worker_event.is_set():
            try:
                doa_data = doa_input_queue.get(timeout=0.2)
            except Empty:
                continue

            fc = doa_data.get("freq")
            signal_sCA = doa_data.get("signal")

            if signal_sCA is None or fc is None:
                continue

            try:
                music_estimator = get_music_estimator(fc)
                estimated_angles = music_estimator.estimate_doa_mean_BF(signal_sCA)

                # --- MUSIC-спектр для heatmap ---
                spectrum = getattr(music_estimator, "_last_spectrum", None)
                if spectrum is not None:
                    try:
                        spec_db = 10.0 * np.log10(spectrum + 1e-20)
                        noise_floor = float(np.percentile(spec_db, 5))
                        peak_db = float(np.max(spec_db))
                        dynamic_range = peak_db - noise_floor
                        if dynamic_range < music_threshold_db:
                            levels = np.zeros(spec_db.shape, dtype=np.uint8)
                        else:
                            norm = np.clip((spec_db - noise_floor) / dynamic_range, 0.0, 1.0)
                            levels = (norm * 255.0).astype(np.uint8)
                        entity = {
                            "freq": float(fc),
                            "n_az": int(spectrum.shape[1]),
                            "n_el": int(spectrum.shape[0]),
                            "levels": levels.flatten().tobytes(),
                            "az_min": float(music_estimator.azimuth_scan[0]),
                            "az_max": float(music_estimator.azimuth_scan[-1]),
                            "el_min": float(music_estimator.elevation_scan[0]),
                            "el_max": float(music_estimator.elevation_scan[-1]),
                        }
                        try:
                            music_spectrum_queue.put_nowait(entity)
                        except Full:
                            try:
                                music_spectrum_queue.get_nowait()
                                music_spectrum_queue.put_nowait(entity)
                            except Exception:
                                pass
                    except Exception:
                        logger.exception("Failed to encode music spectrum")

                if (len(estimated_angles) == 1
                        and estimated_angles[0][0] == music_estimator.no_signal_az
                        and estimated_angles[0][1] == music_estimator.no_signal_el):
                    logger.info("MusicThread: DOA: сигнала нет")
                else:
                    logger.info("MusicThread: Estimated DOA angles (fc=%d): %s", fc, estimated_angles)

                entity = (fc, estimated_angles)
                doa_result_queue.put(entity)
            except Exception:
                logger.exception("Error in MUSIC processing")
    except Exception:
        logger.exception("Fatal error in music_loop")
        end_receiver_worker_event.set()
    finally:
        logger.info("MUSIC loop stopped")


def spectrum_loop():
    logger.info("Spectrum loop started")
    spectrum_window_size = fft.next_fast_len(1024)

    try:
        while not end_receiver_worker_event.is_set():
            try:
                spectrum_entity = spectrum_input_queue.get(timeout=0.2)
            except Empty:
                continue

            sampling_freq = spectrum_entity.get("sampling_rate")
            single_ch = spectrum_entity.get("signal")
            central_freq = spectrum_entity.get("central_freq")

            if single_ch is None or sampling_freq is None or central_freq is None:
                continue

            try:
                N = spectrum_window_size
                noverlap = int(N * 0)
                window = "blackman"

                f, Pxx_den = signal.welch(
                    single_ch, sampling_freq,
                    nperseg=N, nfft=N, noverlap=noverlap,
                    detrend=False, return_onesided=False,
                    window=window, scaling="spectrum",
                )
                spectrum = fft.fftshift(10 * np.log10(Pxx_den))

                spectrum_output_entity = {
                    "central_freq": central_freq,
                    "spectrum": spectrum.astype(np.float32),
                    "samp_freq": sampling_freq,
                }
                spectrum_output_queue.put(spectrum_output_entity)
            except Exception:
                logger.exception("Error while computing spectrum")
    except Exception:
        logger.exception("Fatal error in spectrum_loop")
        end_receiver_worker_event.set()
    finally:
        logger.info("Spectrum loop stopped")


def classification_loop():
    logger.info("Classification loop started")
    top_n = 3

    try:
        while not end_receiver_worker_event.is_set():
            try:
                classification_entity = classification_input_queue.get(timeout=0.2)
            except Empty:
                continue

            input_signal = classification_entity.get("signal")
            sampling_freq = classification_entity.get("sampling_rate")

            if input_signal is None:
                continue

            try:
                signal_for_model = input_signal[:1, :].T
                probabilities = signal_classifier.classify_signal(signal_for_model)
                flat = probabilities.flatten()
                top_n_effective = min(top_n, flat.size)
                top_n_indices = np.argsort(flat)[-top_n_effective:][::-1]
                top_n_labels = [class_labels[i] for i in top_n_indices]
                top_n_probabilities = flat[top_n_indices]

                classification_output_entity = {
                    "top_n_labels": top_n_labels,
                    "top_n_probabilities": top_n_probabilities,
                    "sampling_freq": sampling_freq,
                }
                classification_output_queue.put(classification_output_entity)
            except Exception:
                logger.exception("Error in classification processing")
    except Exception:
        logger.exception("Fatal error in classification_loop")
        end_receiver_worker_event.set()
    finally:
        logger.info("Classification loop stopped")


# ------------------------------- gRPC server -----------------------------

grpc_port = "5005"
grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=50))


class Kraken(kraken_pb2_grpc.KrakenServicer):

    def stop(self, request, context):
        logger.info("Stop command received via gRPC")
        end_receiver_worker_event.set()
        return kraken_pb2.google_dot_protobuf_dot_empty__pb2.Empty()

    def getDoaResult(self, request, context):
        logger.info("getDoaResult stream opened")
        try:
            while context.is_active() and not end_receiver_worker_event.is_set():
                try:
                    data = doa_result_queue.get(timeout=0.2)
                except Empty:
                    continue
                dest_array = kraken_pb2.DOAArray()
                for ang in data[1]:
                    dest_array.destinations.add(a=ang[0], b=ang[1])
                yield kraken_pb2.DOAResult(freq=data[0], res=dest_array)
        except Exception:
            logger.exception("Error in getDoaResult stream")
        finally:
            logger.info("getDoaResult stream closed")

    def getSpectrum(self, request, context):
        logger.info("getSpectrum stream opened")
        try:
            while context.is_active() and not end_receiver_worker_event.is_set():
                try:
                    data = spectrum_output_queue.get(timeout=0.2)
                except Empty:
                    continue
                yield kraken_pb2.SpectrumData(
                    freq=data.get("central_freq"),
                    samp=data.get("samp_freq"),
                    spec=data.get("spectrum"),
                )
        except Exception:
            logger.exception("Error in getSpectrum stream")
        finally:
            logger.info("getSpectrum stream closed")

    def setDaqFrequency(self, request, context):
        target_frequency = request.freq * 1e6
        logger.info("Set DAQ center frequency to %.0f Hz", target_frequency)
        receiver.set_center_freq(target_frequency)
        current_freq = receiver.daq_center_freq
        return kraken_pb2.SetDAQFrequency(freq=current_freq)

    def getClassification(self, request, context):
        if not CLASSIFICATION_ENABLED:
            logger.info("getClassification: отключена")
            return
        logger.info("getClassification stream opened")
        try:
            while context.is_active() and not end_receiver_worker_event.is_set():
                try:
                    data = classification_output_queue.get(timeout=0.2)
                except Empty:
                    continue
                yield kraken_pb2.ClassificationData(
                    names=data.get("top_n_labels"),
                    probs=data.get("top_n_probabilities"),
                )
        except Exception:
            logger.exception("Error in getClassification stream")
        finally:
            logger.info("getClassification stream closed")

    def getMusicSpectrum(self, request, context):
        logger.info("getMusicSpectrum stream opened")
        try:
            while context.is_active() and not end_receiver_worker_event.is_set():
                try:
                    data = music_spectrum_queue.get(timeout=0.5)
                except Empty:
                    continue
                yield kraken_pb2.MusicSpectrumData(
                    freq=data["freq"],
                    n_az=data["n_az"],
                    n_el=data["n_el"],
                    levels=data["levels"],
                    az_min=data["az_min"],
                    az_max=data["az_max"],
                    el_min=data["el_min"],
                    el_max=data["el_max"],
                )
        except Exception:
            logger.exception("Error in getMusicSpectrum stream")
        finally:
            logger.info("getMusicSpectrum stream closed")

    def getMusicThreshold(self, request, context):
        """Возвращает текущий порог нормализации MUSIC-спектра."""
        return kraken_pb2.MusicThresholdResponse(
            threshold_db=float(music_threshold_db),
            success=True,
        )

    def setMusicThreshold(self, request, context):
        """Устанавливает новый порог нормализации."""
        global music_threshold_db
        new_val = float(request.threshold_db)
        if new_val < 0.0:
            new_val = 0.0
        if new_val > 30.0:
            new_val = 30.0
        music_threshold_db = new_val
        logger.info("Music threshold set to %.2f dB", music_threshold_db)
        return kraken_pb2.MusicThresholdResponse(
            threshold_db=music_threshold_db,
            success=True,
        )

    def setRecording(self, request, context):
        try:
            if request.enabled:
                path = recording_state.start(request.filename)
                return kraken_pb2.SetRecordingResponse(
                    enabled=True, path=path,
                    frames_written=recording_state.frame_counter,
                )
            else:
                path = recording_state.stop()
                return kraken_pb2.SetRecordingResponse(
                    enabled=False, path=path or "",
                    frames_written=recording_state.frame_counter,
                )
        except Exception:
            logger.exception("Error in setRecording")
            return kraken_pb2.SetRecordingResponse(
                enabled=False, path="", frames_written=0
            )

    # ---------- Antenna presets ----------

    def getAntennaPresets(self, request, context):
        presets = []
        for key, p in ANTENNA_PRESETS.items():
            presets.append(kraken_pb2.AntennaPresetInfo(
                key=key,
                name=p["name"],
                active=(key == current_preset_key),
            ))
        return kraken_pb2.AntennaPresetList(presets=presets)

    def setAntennaPreset(self, request, context):
        ok = set_antenna_preset(request.key)
        p = ANTENNA_PRESETS.get(request.key)
        if ok and p is not None:
            return kraken_pb2.SetAntennaPresetResponse(
                success=True, key=request.key, name=p["name"],
            )
        return kraken_pb2.SetAntennaPresetResponse(
            success=False, key="", name="",
        )


def grpc_start():
    kraken_pb2_grpc.add_KrakenServicer_to_server(Kraken(), grpc_server)
    grpc_server.add_insecure_port("[::]:" + grpc_port)
    grpc_server.start()
    logger.info("gRPC server started at port %s", grpc_port)


# ------------------------------- main ------------------------------------


def main():
    logger.info("Application starting")

    receiver_worker = Thread(target=receiver_loop, name="ReceiverThread", daemon=True)
    music_worker = Thread(target=music_loop, name="MusicThread", daemon=True)
    spectrum_worker = Thread(target=spectrum_loop, name="SpectrumThread", daemon=True)

    receiver_worker.start()
    music_worker.start()
    spectrum_worker.start()

    if CLASSIFICATION_ENABLED:
        classification_worker = Thread(
            target=classification_loop, name="ClassificationThread", daemon=True
        )
        classification_worker.start()
    else:
        classification_worker = None

    grpc_start()

    try:
        while not end_receiver_worker_event.is_set():
            time.sleep(0.3)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received, stopping...")
        end_receiver_worker_event.set()
    finally:
        logger.info("Shutting down...")

        if recording_state.enabled:
            recording_state.stop()

        receiver_worker.join(timeout=2.0)
        music_worker.join(timeout=2.0)
        spectrum_worker.join(timeout=2.0)
        if classification_worker is not None:
            classification_worker.join(timeout=2.0)

        grpc_server.stop(grace=1)
        grpc_server.wait_for_termination()

        logger.info("Application stopped")


if __name__ == "__main__":
    main()