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

from classify_signal import classify_signal

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

# Очередь от приёмника IQ данных
data_que = Queue(maxsize=5)

# Ресивер: тип соединения и IP адрес
receiver = ReceiverRTLSDR(data_que, "eth", "127.0.0.1")

# Событие для корректной остановки всех потоков
end_receiver_worker_event = Event()
end_receiver_worker_event.clear()

# Очереди обмена данными между потоками
doa_result_queue = Queue()
doa_input_queue = Queue(maxsize=5)
spectrum_input_queue = Queue(maxsize=5)
spectrum_output_queue = Queue(maxsize=5)

classification_input_queue = Queue(maxsize=3)
classification_output_queue = Queue(maxsize=3)


# Блокировка для операций с ресивером (частота и т.д.)
receiver_lock = Lock()

# Предыдущее состояние синхронизации (для отслеживания переходов)
prev_sync_ok = None

# ------------------------ Параметры антенной решётки --------------------

# Позиции элементов антенны (пример – крест Миллса)  ДРОН
x_a = np.array([ 0,     0,  0,     -0.005,   0])
y_a = np.array([-0.24,  0,  0.145,  0,   0])
z_a = np.array([ 0,     0,  0,     0.235, 0.37])

# Задание позиций элементов в виде массива (x, y, z)
element_positions = np.vstack([x_a, y_a, z_a])

# Создаем объект массива антенн
sensor_array = SensorArray(element_positions)

# Количество искомых сигналов
num_signals = 1

# Диапазоны для поиска DOA
azimuth_scan = np.linspace(0, 180, 181)     # Азимут
elevation_scan = np.linspace(-60, 60, 121)   # Возвышение

# режим калибровки антенн:
# False – обычная работа
# True  – в лог вываливается табличка мощностей по каналам/координатам
CALIBRATION_MODE = True  # включи True, когда будешь проверять элементы


# ------------------------ Параметры обработки сигналов ------------------

# Желаемая частота дискретизации для нейросети (400 кГц)
target_fs_network = 40e4

# Желаемая частота дискретизации для пеленгатора MUSIC
target_fs_music = 2.4e6

# Количество отсчетов для DOA
n_samp = 1024 * 3000

# Количество отсчетов для классификации
n_samp_net = 1024 * 1

# ---------------------- Модель классификации сигналов -------------------

onnx_model_path = "signalClassificationModel_quantized_V1.onnx"

class_labels = [
    "2G", "5G", "AM_Radio", "Bluetooth", "DECT",
    "DVB_T2", "EDGE", "FM_Radio", "GPS", "GSM",
    "LTE", "LoRa", "NB_IoT", "Satellite_Communication",
    "TETRA", "WiMax", "Wi_Fi", "ZigBee",
]

signal_classifier = classify_signal(onnx_model_path, class_labels)

# --------------------- Кеш объектов MUSIC для разных частот -------------

music_estimators = {}



def get_music_estimator(fc: float) -> MUSIC2D:
    """
    Возвращает (или создаёт) экземпляр MUSIC2D для заданной центральной частоты.

    Используем кеш, чтобы не пересоздавать тяжёлый объект при каждой обработке.
    """
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


# ----------------------------- Потоки обработки -------------------------


def receiver_loop():
    """
    Основной поток приёма IQ-данных от ресивера.

    Читает данные из ресивера, формирует структуры для:
    - оценки направления (MUSIC),
    - построения спектра,
    - классификации сигналов,
    и отправляет их в соответствующие очереди.
    """
    logger.info("Receiver loop started")
    global prev_sync_ok

    try:
        while not end_receiver_worker_event.is_set():
            # Получаем IQ-данные от ресивера
            with receiver_lock:
                get_iq_failed = receiver.get_iq_online()
                iq_header: IQHeader = receiver.iq_header
                iq_samples = receiver.iq_samples
                sampling_freq = iq_header.sampling_freq if iq_header else None
                fc = receiver.daq_center_freq

            # ---------- Лог заголовка и переходов синхронизации ----------
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
                    "SYNC STATE CHANGED: frame=%d %s → %s "
                    "(delay_sync=%d, iq_sync=%d, frame_type=%d, noise=%d)",
                    iq_header.cpi_index,
                    prev_sync_ok,
                    cur_sync_ok,
                    iq_header.delay_sync_flag,
                    iq_header.iq_sync_flag,
                    iq_header.frame_type,
                    iq_header.noise_source_state,
                )
                iq_header.log_sync_status(logger, level=logging.WARNING)
                prev_sync_ok = cur_sync_ok

            # ---------- Проверяем, есть ли вообще данные ----------
            # get_iq_failed: драйвер сказал, что чтение не удалось
            if get_iq_failed:
                time.sleep(0.01)
                continue

            # На некоторых кадрах (DUMMY/служебные) iq_samples может быть int, а не массив
            if not isinstance(iq_samples, np.ndarray):
                logger.debug(
                    "Receiver: iq_samples is %r (type=%s) for frame_type=%d, skipping",
                    iq_samples, type(iq_samples), iq_header.frame_type
                )
                time.sleep(0.01)
                continue

            if iq_samples.size == 0:
                time.sleep(0.01)
                continue

            if not iq_header.is_valid:
                logger.warning("Receiver: invalid sync_word, frame=%d", iq_header.cpi_index)
                continue

            # Для всех дальнейших действий используем только DATA-кадры
            if not iq_header.is_data_frame:
                logger.debug(
                    "Receiver: non-data frame type=%d (frame=%d), skipping processing",
                    iq_header.frame_type, iq_header.cpi_index
                )
                time.sleep(0.01)
                continue

            # Теперь мы уверены, что:
            # - есть валидный заголовок
            # - есть numpy-массив iq_samples
            # - frame_type == DATA

            processed_signal = np.ascontiguousarray(iq_samples)

            # ---------- Блок DOA / MUSIC: только если can_use_for_music ----------
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
                            calib_chunk,
                            logger=calib_logger,
                            normalize=True,
                        )

                    #try:
                    #    signal_sCA = sensor_array.resample_signal(
                    #        complex_data, sampling_freq, target_fs_music
                    #    )
                    #except Exception:
                    #    logger.exception("Error while resampling signal for MUSIC")
                    #    signal_sCA = None

                    signal_sCA = complex_data

                    if signal_sCA is not None:
                        doa_input_entity = {
                            "signal": signal_sCA,
                            "freq": fc,
                        }
                        try:
                            doa_input_queue.put_nowait(doa_input_entity)
                        except Full:
                            logger.debug("DOA input queue is full, dropping frame")
            else:
                # Синхры нет — DOA не считаем, но спектр/классификацию можно оставить
                logger.info(
                    "Receiver: frame %d not suitable for MUSIC "
                    "(sync_ok=%s, frame_type=%d)",
                    iq_header.cpi_index,
                    iq_header.sync_ok,
                    iq_header.frame_type,
                )

            # ---------- Спектр и классификация: только по DATA-кадрам ----------
            try:
                single_ch = processed_signal[1, :]
            except Exception:
                logger.exception("Error extracting single channel from IQ")
                continue

            spectrum_input_entity = {
                "sampling_rate": sampling_freq,
                "signal": single_ch,
                "central_freq": fc,
            }
            try:
                spectrum_input_queue.put_nowait(spectrum_input_entity)
            except Full:
                logger.debug("Spectrum input queue is full, dropping frame")

            classification_input_entity = {
                "signal": processed_signal[:, :n_samp_net],
                "sampling_rate": sampling_freq,
            }
            try:
                classification_input_queue.put_nowait(classification_input_entity)
            except Full:
                logger.debug("Classification input queue is full, dropping frame")

    except Exception:
        logger.exception("Fatal error in receiver_loop")
        end_receiver_worker_event.set()
    finally:
        logger.info("Receiver loop stopped")


def music_loop():
    """
    Поток, выполняющий оценку направления прихода сигнала (DOA)
    методом MUSIC по данным из очереди doa_input_queue.
    """
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
                logger.warning("Invalid DOA data: %s", doa_data)
                continue

            try:
                music_estimator = get_music_estimator(fc)

                # Оценка углов прихода (DOA)
                estimated_angles = music_estimator.estimate_doa_mean_BF(signal_sCA)
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
    """
    Поток, вычисляющий спектр сигнала методом Welch
    и отправляющий его в очередь spectrum_output_queue.
    """
    logger.info("Spectrum loop started")
    spectrum_window_size = fft.next_fast_len(4096)

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
                logger.warning("Invalid spectrum data: %s", spectrum_entity)
                continue

            try:
                N = spectrum_window_size

                noverlap = int(N * 0)
                window = "blackman"

                f, Pxx_den = signal.welch(
                    single_ch,
                    sampling_freq,
                    nperseg=N,
                    nfft=N,
                    noverlap=noverlap,
                    detrend=False,
                    return_onesided=False,
                    window=window,
                    scaling="spectrum",
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
    """
    Поток классификации сигналов с использованием ONNX-модели.

    Берёт сигналы из очереди classification_input_queue,
    запускает классификацию и публикует результат
    (топ-N классов) в classification_output_queue.
    """
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
                logger.warning("Invalid classification data: %s", classification_entity)
                continue

            try:
                # Здесь можно добавить реальный ресемплинг до target_fs_network, если
                # модель была обучена на фиксированной частоте. Пока используем как есть.

                # Используем только первый канал и транспонируем данные
                # до формы (num_samples, 1), если это требуется моделью.
                signal_for_model = input_signal[:1, :].T

                probabilities = signal_classifier.classify_signal(signal_for_model)

                # Получаем индексы топ-N классов по убыванию вероятности
                flat = probabilities.flatten()
                if flat.size < top_n:
                    logger.warning(
                        "Probabilities size smaller than top_n: %d < %d",
                        flat.size,
                        top_n,
                    )
                    top_n_effective = flat.size
                else:
                    top_n_effective = top_n

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
grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))


class Kraken(kraken_pb2_grpc.KrakenServicer):
    """
    Реализация gRPC-сервиса Kraken для:
    - управления остановкой,
    - получения результатов DOA,
    - получения спектра,
    - установки частоты выборки ресивера,
    - получения результатов классификации.
    """

    def stop(self, request, context):
        """
        Остановка всей программы.
        """
        logger.info("Stop command received via gRPC")
        end_receiver_worker_event.set()
        return kraken_pb2.google_dot_protobuf_dot_empty__pb2.Empty()

    def getDoaResult(self, request, context):
        """
        Потоковая выдача результатов DOA.
        """
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
        """
        Потоковая выдача спектров сигнала.
        """
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
        """
        Установка центральной частоты ресивера (в МГц).
        """
        target_frequency = request.freq * 1e6
        logger.info("Set DAQ center frequency to %.0f Hz", target_frequency)
        with receiver_lock:
            receiver.set_center_freq(target_frequency)
            current_freq = receiver.daq_center_freq
        return kraken_pb2.SetDAQFrequency(freq=current_freq)

    def getClassification(self, request, context):
        """
        Потоковая выдача результатов классификации сигналов.
        """
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


def grpc_start():
    """
    Инициализация и запуск gRPC-сервера.
    """
    kraken_pb2_grpc.add_KrakenServicer_to_server(Kraken(), grpc_server)
    grpc_server.add_insecure_port("[::]:" + grpc_port)
    grpc_server.start()
    logger.info("gRPC server started at port %s", grpc_port)


# ------------------------------- main ------------------------------------


def main():
    logger.info("Application starting")

    # Запускаем потоки обработки
    receiver_worker = Thread(target=receiver_loop, name="ReceiverThread", daemon=True)
    music_worker = Thread(target=music_loop, name="MusicThread", daemon=True)
    spectrum_worker = Thread(target=spectrum_loop, name="SpectrumThread", daemon=True)
    classification_worker = Thread(
        target=classification_loop, name="ClassificationThread", daemon=True
    )

    receiver_worker.start()
    music_worker.start()
    spectrum_worker.start()
    classification_worker.start()

    # Запускаем gRPC сервер
    grpc_start()

    try:
        # Основной поток просто ждёт сигнала завершения
        while not end_receiver_worker_event.is_set():
            time.sleep(0.3)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received, stopping...")
        end_receiver_worker_event.set()
    finally:
        logger.info("Shutting down...")

        # Даем потокам время корректно завершиться
        receiver_worker.join(timeout=2.0)
        music_worker.join(timeout=2.0)
        spectrum_worker.join(timeout=2.0)
        classification_worker.join(timeout=2.0)

        grpc_server.stop(grace=1)
        grpc_server.wait_for_termination()

        logger.info("Application stopped")


if __name__ == "__main__":
    main()
