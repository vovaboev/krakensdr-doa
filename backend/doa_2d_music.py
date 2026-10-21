import logging
from typing import Optional, List, Tuple

import numpy as np
from numpy.linalg import svd

from scipy.constants import speed_of_light
from scipy.ndimage import maximum_filter
import scipy.signal

logger = logging.getLogger(__name__)


class SensorArray:
    def __init__(self, element_positions: np.ndarray):
        """
        Класс антенной решётки с произвольными позициями элементов.

        Parameters
        ----------
        element_positions : np.ndarray
            Массив формы (3, N):
            - первая ось: координаты (x, y, z),
            - вторая ось: номер элемента (N элементов).
        """
        if element_positions.ndim != 2 or element_positions.shape[0] != 3:
            raise ValueError(
                "element_positions должен быть формы (3, N), "
                "получено %s" % (element_positions.shape,)
            )

        self.element_positions = element_positions
        self.num_elements = element_positions.shape[1]

        logger.debug(
            "SensorArray инициализирован: %d элементов", self.num_elements
        )

    # ------------------------------------------------------------------ #
    #            Базовые методы работы с антенной решёткой               #
    # ------------------------------------------------------------------ #

    def get_element_positions(self) -> np.ndarray:
        """
        Возвращает позиции элементов антенны (3, N).
        """
        return self.element_positions

    def get_steering_vector(
        self, azimuth_deg: float, elevation_deg: float, fc: float
    ) -> np.ndarray:
        """
        Вычисление вектора направленности (steering vector) для задданых
        азимута и угла места.

        Parameters
        ----------
        azimuth_deg : float
            Азимут в градусах.
        elevation_deg : float
            Угол места (возвышение) в градусах.
        fc : float
            Частота сигнала в Гц.

        Returns
        -------
        np.ndarray
            Вектор направленности формы (N_elements,).
        """
        # Преобразование углов в радианы
        az_rad = np.deg2rad(azimuth_deg)
        el_rad = np.deg2rad(elevation_deg)

        # Длина волны
        lam = speed_of_light / fc

        # Для креста в плоскости YZ:
        # k = [cos(el)*sin(az), cos(el)*cos(az), sin(el)]
        kx = np.cos(el_rad) * np.sin(az_rad)
        ky = np.cos(el_rad) * np.cos(az_rad)
        kz = np.sin(el_rad)

        # Скалярное произведение k·r для каждого элемента
        positions = self.element_positions  # (3, N)
        phase = kx * positions[0, :] + ky * positions[1, :] + kz * positions[2, :]

        steering_vector = np.exp(1j * 2 * np.pi * phase / lam)
        return steering_vector

    def generate_signal(
        self, Nsamp: int, angs: np.ndarray, noisePwr: float, fc: float
    ) -> np.ndarray:
        """
        Генерация искусственного сигнала для массива антенн с заданными
        углами прихода и аддитивным белым шумом.

        Parameters
        ----------
        Nsamp : int
            Количество отсчётов.
        angs : np.ndarray
            Массив формы (2, num_signals):
            [0, i] — азимут в градусах,
            [1, i] — угол места в градусах.
        noisePwr : float
            Мощность шума (на элемент).
        fc : float
            Частота сигнала в Гц.

        Returns
        -------
        np.ndarray
            Сгенерированный сигнал формы (N_elements, Nsamp).
        """
        if angs.shape[0] != 2:
            raise ValueError("angs должен иметь форму (2, num_signals)")

        num_signals = angs.shape[1]

        signal = np.zeros((self.num_elements, Nsamp), dtype=np.complex128)

        for i in range(num_signals):
            az = angs[0, i]
            el = angs[1, i]
            steering = self.get_steering_vector(az, el, fc)

            # Случайный комплексный сигнал
            random_signal = (
                np.random.randn(Nsamp) + 1j * np.random.randn(Nsamp)
            ) / np.sqrt(2.0)
            signal += np.outer(steering, random_signal)

        # Комплексный белый гауссов шум
        noise = np.sqrt(noisePwr / 2.0) * (
            np.random.randn(self.num_elements, Nsamp)
            + 1j * np.random.randn(self.num_elements, Nsamp)
        )
        signal += noise

        logger.debug(
            "Сгенерирован тестовый сигнал: Nsamp=%d, num_signals=%d, noisePwr=%.2e",
            Nsamp,
            num_signals,
            noisePwr,
        )

        return signal

    def resample_signal(
        self, complex_data: np.ndarray, originalFs: float, targetFs: float
    ) -> np.ndarray:
        """
        Ресемплинг многоканального комплексного сигнала до требуемой частоты.

        Ожидается вход формы (N_channels, Nsamp).

        Parameters
        ----------
        complex_data : np.ndarray
            Комплексный сигнал формы (N_channels, Nsamp).
        originalFs : float
            Исходная частота дискретизации.
        targetFs : float
            Желаемая частота дискретизации.

        Returns
        -------
        np.ndarray
            Ресемплированный сигнал формы (N_channels, Nsamp_resampled).
        """
        if complex_data.ndim != 2:
            raise ValueError("complex_data должен быть формы (N_channels, Nsamp)")

        if originalFs <= 0 or targetFs <= 0:
            raise ValueError("Частоты дискретизации должны быть > 0")

        num_samples = int(
            max(1, round(complex_data.shape[1] * targetFs / originalFs))
        )

        logger.debug(
            "Ресемплинг: %d → %d отсчётов (Fs: %.1f → %.1f кГц)",
            complex_data.shape[1],
            num_samples,
            originalFs / 1e3,
            targetFs / 1e3,
        )

        resampled_signal = scipy.signal.resample(
            complex_data, num_samples, axis=1
        )
        return resampled_signal
    
    def debug_channel_powers(self, signal: np.ndarray, logger=None, normalize=True):
        """
        Диагностический вывод: для каждого элемента массива печатает
        его индекс, координаты (x, y, z) и мощность канала.

        Это удобно использовать при калибровке:
        - закрываешь/экранируешь один элемент (рукой, металлом)
        - смотришь, у какого канала в таблице мощность сильно упала
        - по координатам понимаешь, какой физический элемент за какой канал отвечает.

        Parameters
        ----------
        signal : np.ndarray
            Массив комплексных отсчётов формы (M, N),
            где M = число элементов (каналов), N = число отсчётов во времени.
        logger : logging.Logger или None
            Если передан logger, вывод пойдёт через logger.info.
            Если None — вывод через print().
        normalize : bool
            Если True — дополнительно выводит мощность в dB
            относительно максимального канала (макс = 0 dB).
        """
        if signal.ndim != 2:
            raise ValueError(
                f"Ожидался signal формы (M, N), а получено shape={signal.shape}"
            )

        M, N = signal.shape
        if M != self.num_elements:
            raise ValueError(
                f"Число строк в signal (M={M}) не совпадает с числом элементов массива "
                f"(num_elements={self.num_elements}). Проверь порядок каналов!"
            )

        # Средняя мощность по каждому каналу: E{|x|^2}
        powers = np.mean(np.abs(signal) ** 2, axis=1)  # shape (M,)

        # Относительная шкала в dB (максимальный канал = 0 dB)
        if normalize:
            max_p = float(np.max(powers) + 1e-20)
            powers_db = 10.0 * np.log10(powers / max_p + 1e-20)
        else:
            powers_db = None

        pos = self.element_positions  # shape (3, M) → (x,y,z) для каждого элемента

        # Формируем табличку строками
        lines = []
        lines.append("")  # пустая строка перед блоком
        if normalize:
            lines.append(
                "Диагностика мощностей по каналам (относительно максимального канала):"
            )
        else:
            lines.append("Диагностика мощностей по каналам:")

        if normalize:
            lines.append(
                "Ch |      x    |      y    |      z    |   Power (lin)  | Power (rel dB)"
            )
            lines.append(
                "---+-----------+-----------+-----------+---------------+---------------"
            )
        else:
            lines.append(
                "Ch |      x    |      y    |      z    |   Power (lin)"
            )
            lines.append(
                "---+-----------+-----------+-----------+---------------"
            )

        for ch in range(M):
            x, y, z = pos[0, ch], pos[1, ch], pos[2, ch]
            p_lin = float(powers[ch])
            if normalize:
                p_db = float(powers_db[ch])
                lines.append(
                    f"{ch:2d} | {x:9.3f} | {y:9.3f} | {z:9.3f} | {p_lin:13.3e} | {p_db:13.2f}"
                )
            else:
                lines.append(
                    f"{ch:2d} | {x:9.3f} | {y:9.3f} | {z:9.3f} | {p_lin:13.3e}"
                )

        text = "\n".join(lines)

        if logger is not None:
            logger.info(text)
        else:
            print(text)

        # На всякий случай возвращаем числовые значения,
        return powers, powers_db


class MUSIC2D:
    def __init__(
        self,
        sensor_array: SensorArray,
        fc: float,
        azimuth_scan: np.ndarray,
        elevation_scan: np.ndarray,
        num_signals: int = 1,
        diag_log: bool = True,
        diag_top_n: int = 10,
    ):
        """
        2D MUSIC-пеленгатор.

        Parameters
        ----------
        sensor_array : SensorArray
            Антенная решётка.
        fc : float
            Центральная частота сигнала в Гц.
        azimuth_scan : np.ndarray
            Вектор азимутов (в градусах) для сканирования.
        elevation_scan : np.ndarray
            Вектор углов места (в градусах) для сканирования.
        num_signals : int
            Ожидаемое количество сигналов (источников).
        diag_log : bool
            Включить подробный диагностический лог по спектру.
        diag_top_n : int
            Сколько топ-пиков спектра выводить в диагностике.
        """
        self.sensor_array = sensor_array
        self.fc = fc
        self.wavelength = speed_of_light / fc
        self.azimuth_scan = np.array(azimuth_scan, dtype=float)
        self.elevation_scan = np.array(elevation_scan, dtype=float)

        self.num_signals = int(num_signals)
        
        # --- Пороги детекции ---
        # 1. Минимальное PNR (peak-to-noise ratio), ниже которого считаем, что сигнала нет
        self.min_peak_to_noise_db = 0.085  # dB, подбирается по логам

        # 2. Насколько dB ниже главного пика допускаем «настоящие» локальные пики
        #    (для одного источника 4–8 dB обычно достаточно)
        self.local_peak_rel_db = 6.0     # dB

        # Специальные значения "нет сигнала"
        self.no_signal_az = -909.0
        self.no_signal_el = -999.0

        # Диагностика
        self.diag_log = bool(diag_log)
        self.diag_top_n = int(diag_top_n)

        self.steering_vectors = None
        self.precompute_steering_vectors()

        logger.info(
            "MUSIC2D инициализирован: fc=%.3f МГц, азимуты=%d, углы=%d, "
            "ожидаемых сигналов=%d, diag=%s",
            fc / 1e6,
            self.azimuth_scan.size,
            self.elevation_scan.size,
            self.num_signals,
            self.diag_log,
        )

    # ------------------------------------------------------------------ #
    #                  Предрасчёт steering-векторов                      #
    # ------------------------------------------------------------------ #

    def precompute_steering_vectors(self) -> None:
        """
        Предвычисляет steering-векторы для всех комбинаций азимута и угла места.

        Результат:
        self.steering_vectors имеет форму (N_el, N_az, N_ant),
        где N_el — число точек по углу места,
              N_az — число точек по азимуту,
              N_ant — число элементов решётки.
        """
        az = self.azimuth_scan
        el = self.elevation_scan

        az_mesh, el_mesh = np.meshgrid(az, el)  # в градусах
        az_flat = az_mesh.ravel()
        el_flat = el_mesh.ravel()

        logger.debug(
            "Предрасчёт steering-векторов: %d×%d = %d точек сканирования",
            el.size,
            az.size,
            az_flat.size,
        )

        steering_flat = np.array(
            [
                self.sensor_array.get_steering_vector(az_deg, el_deg, self.fc)
                for az_deg, el_deg in zip(az_flat, el_flat)
            ]
        )  # (N_el*N_az, M)

        self.steering_vectors = steering_flat.reshape(
            el.size, az.size, -1
        )

    # ------------------------------------------------------------------ #
    #                   Ковариация и пороги (SVD)                        #
    # ------------------------------------------------------------------ #

    def estimate_covariance_matrix(self, signal: np.ndarray) -> np.ndarray:
        """
        Оценка ковариационной матрицы сигнала.

        Parameters
        ----------
        signal : np.ndarray
            Матрица сигналов формы (N_elements, N_samples).

        Returns
        -------
        np.ndarray
            Ковариационная матрица (N_elements, N_elements).
        """
        if signal.ndim != 2:
            raise ValueError("signal должен быть формы (N_elements, N_samples)")

        R = signal @ signal.conj().T / signal.shape[1]
        return R

    def adaptive_threshold(self, S: np.ndarray) -> float:
        """
        Порог для разделения сигнал/шум по сингулярным значениям (запасной метод).
        """
        mean_s = np.mean(S)
        std_s = np.std(S)
        threshold = mean_s + 0.7 * std_s
        return threshold

    def adaptive_threshold_music(self, eigvals: np.ndarray) -> float:
        """
        Порог для разделения сигнал/шум по собственным значениям ковариационной матрицы.

        Использует комбинацию квартилей и дисперсии.
        """
        S = np.abs(eigvals)
        q1 = np.percentile(S, 25)
        q3 = np.percentile(S, 75)
        iqr = q3 - q1
        threshold = q3 + np.std(S) * iqr
        return threshold

    # ------------------------------------------------------------------ #
    #                          MUSIC спектр                              #
    # ------------------------------------------------------------------ #

    def music_spectrum_fast(
        self,
        signal: Optional[np.ndarray] = None,
        covariance_matrix: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """
        Быстрая векторизованная оценка MUSIC-спектра.

        Parameters
        ----------
        signal : np.ndarray, optional
            Сигнал формы (N_elements, N_samples). Если передан, будет
            оценена ковариационная матрица.
        covariance_matrix : np.ndarray, optional
            Предрасчитанная ковариационная матрица (N_elements, N_elements).

        Returns
        -------
        np.ndarray
            2D MUSIC-спектр формы (N_el, N_az).
        """
        if covariance_matrix is None:
            if signal is None:
                raise ValueError("Нужно передать либо signal, либо covariance_matrix")
            covariance_matrix = self.estimate_covariance_matrix(signal)

        # Для эрмитовой ковариационной матрицы лучше использовать eigh
        eigvals, eigvecs = np.linalg.eigh(covariance_matrix)

        threshold = self.adaptive_threshold_music(eigvals)

        sort_idx = np.argsort(eigvals)[::-1]
        eigvals = eigvals[sort_idx]
        eigvecs = eigvecs[:, sort_idx]

        M = covariance_matrix.shape[0]
        num_signals = self.num_signals
        if num_signals <= 0 or num_signals >= M:
            num_signals = int(np.sum(np.abs(eigvals) > threshold))
            num_signals = min(max(num_signals, 1), M - 1)

        noise_subspace = eigvecs[:, num_signals:]  # (M, M-num_signals)

        sv = self.steering_vectors.reshape(-1, self.steering_vectors.shape[-1])

        proj = noise_subspace.conj().T @ sv.T  # (M-num_signals, N_el*N_az)
        denom = np.sum(np.abs(proj) ** 2, axis=0)  # (N_el*N_az,)

        spectrum = 1.0 / (denom + 1e-12)
        spectrum = spectrum.reshape(
            self.steering_vectors.shape[0],
            self.steering_vectors.shape[1],
        )

        return spectrum

    # ------------------------------------------------------------------ #
    #                      Оценка DOA + поиск пиков                      #
    # ------------------------------------------------------------------ #

    def estimate_doa_mean_BF(
        self,
        signal: np.ndarray,
        fs: float = 2.4e6,
        frames_len: int = 1024 * 10,
        use_weights: bool = True,
        forward_backward: bool = False,
        spatial_smoothing_size: int = 0,
    ) -> List[Tuple[float, float]]:
        """
        Оценка направлений прихода (DOA) по 2D MUSIC c:
        - возможным forward-backward усреднением,
        - пространственным сглаживанием,
        - робастным взвешиванием кадров.

        Parameters
        ----------
        signal : np.ndarray
            Сигнал формы (N_elements, N_samples).
        fs : float
            Частота дискретизации, Гц (диагностика).
        frames_len : int
            Длина кадра для оценки ковариации.
        use_weights : bool
            Использовать адаптивное взвешивание кадров по мощности.
        forward_backward : bool
            Включить forward-backward обработку (J R* J).
        spatial_smoothing_size : int
            Размер подмассива для пространственного сглаживания.

        Returns
        -------
        List[Tuple[float, float]]
            [(азимут_град, угол_места_град), ...]
        """
        if signal.ndim != 2:
            raise ValueError("signal должен быть формы (N_elements, N_samples)")

        M, total_samples = signal.shape
        samples_per_frame = frames_len
        num_frames = total_samples // samples_per_frame

        logger.info(
            "Запуск DOA: M=%d, Fs=%.1f МГц, кадров=%d, длина кадра=%d (%.1f мс)",
            M,
            fs / 1e6,
            num_frames,
            frames_len,
            frames_len / fs * 1000.0,
        )

        if num_frames == 0:
            logger.error("Нет ни одного полного кадра для оценки DOA")
            return []

        # --- 1. Статистика мощности по кадрам ---
        all_powers = []
        for i in range(num_frames):
            frame = signal[:, i * samples_per_frame : (i + 1) * samples_per_frame]  # (M, N)
            power = np.mean(np.abs(frame) ** 2)  # средняя мощность на отсчёт
            all_powers.append(power)

        all_powers = np.array(all_powers)
        median_power = np.median(all_powers)


        if num_frames < 5:
            # Статистики мало — особо не доверяем оценке σ, просто логируем факт.
            sigma_est = median_power  # условно SNR≈0 дБ
            logger.debug(
                "Мало кадров (%d), грубая оценка sigma_est = median_power = %.2e",
                num_frames, sigma_est
            )
        else:
            mad_power = np.median(np.abs(all_powers - median_power))
            sigma_est = 1.4826 * mad_power + 1e-12

        logger.debug(
            "Статистика по кадрам: медианная мощность=%.2e, σ≈%.2e, медианный SNR≈%.1f дБ",
            median_power,
            sigma_est,
            20 * np.log10(median_power / sigma_est + 1e-9),
        )

        # --- 2. Накопление ковариации ---
        R_acc = np.zeros((M, M), dtype=np.complex128)
        weight_sum = 0.0
        skipped_low = 0
        used_frames = 0

        log_step = max(1, num_frames // 10)

        for i in range(num_frames):
            start = i * samples_per_frame
            end = start + samples_per_frame
            frame = signal[:, start:end]

            frame_power = np.sum(np.abs(frame) ** 2) / frame.size
            relative_power = (frame_power - median_power) / sigma_est

            if use_weights:
                weight = np.tanh(relative_power * 0.6) + 1.2
                weight = max(weight, 0.05)
            else:
                weight = 1.0

            if frame_power < median_power * 0.01:
                skipped_low += 1
                continue

            R_f = (frame @ frame.conj().T) / frame.shape[1]

            if forward_backward:
                # Матрица J для FB-обработки (борьба с мультипутём)
                J = np.flipud(np.eye(M, dtype=np.float64))
                # Классическое FB-усреднение: R_FB = 0.5*(R + J R* J)
                R_frame = 0.5 * (R_f + J @ R_f.conj() @ J)
            else:
                R_frame = R_f

            if 2 <= spatial_smoothing_size < M:
                R_frame = self._spatial_smoothing(
                    R_frame, subarray_size=spatial_smoothing_size
                )

            R_acc += weight * R_frame
            weight_sum += weight
            used_frames += 1

            if (i + 1) % log_step == 0 or i < 3:
                snr_db = 20 * np.log10(frame_power / sigma_est + 1e-9)
                logger.debug(
                    "Кадр %3d/%3d | P=%.2e | SNR≈%+5.1f дБ | вес=%.2f",
                    i + 1,
                    num_frames,
                    frame_power,
                    snr_db,
                    weight,
                )

        logger.debug(
            "Использовано кадров: %d/%d (пропущено слабых: %d)",
            used_frames,
            num_frames,
            skipped_low,
        )

        if weight_sum < 1e-12:
            logger.error("Все кадры были отброшены — невозможно оценить DOA")
            return []

        R = R_acc / weight_sum
        logger.debug("Ковариационная матрица сформирована")

        # --- 3. MUSIC-спектр ---
        spectrum = self.music_spectrum_fast(covariance_matrix=R)
        max_val = np.max(spectrum)
        logger.info("MUSIC: максимальное значение спектра = %.3e", max_val)

        # Диагностический вывод топ-N по всему спектру
        if self.diag_log and self.diag_top_n > 0:
            flat = spectrum.ravel()
            top_n = min(self.diag_top_n, flat.size)
            top_idx = np.argsort(flat)[::-1][:top_n]

            lines = []
            lines.append("")  # пустая строка перед блоком
            lines.append(f"TOP-{top_n} значений MUSIC-спектра (глобально по сетке):")
            lines.append("  # |   Az, ° |   El, ° |      Power |  Power, dB")
            lines.append("----+--------+--------+-----------+-----------")

            for rank, linear_idx in enumerate(top_idx, start=1):
                el_idx, az_idx = np.unravel_index(linear_idx, spectrum.shape)
                az = float(self.azimuth_scan[az_idx])
                el = float(self.elevation_scan[el_idx])
                val = float(flat[linear_idx])
                val_db = 10 * np.log10(val + 1e-20)

                lines.append(
                    f"{rank:3d} | {az:7.1f} | {el:7.1f} | {val:10.3e} | {val_db:10.2f}"
                )

            logger.debug("\n".join(lines))


        az_scan = np.asarray(self.azimuth_scan, dtype=float)
        el_scan = np.asarray(self.elevation_scan, dtype=float)

        if len(az_scan) < 2 or len(el_scan) < 2:
            logger.error("Сетка сканирования слишком грубая или пустая")
            return []

        # --- 4. Поиск локальных максимумов 2D ---
        az_step = np.median(np.diff(az_scan)) if len(az_scan) > 1 else 1.0
        el_step = np.median(np.diff(el_scan)) if len(el_scan) > 1 else 1.0
        min_sep_deg = 4.0  # минимальное расстояние между пиками (по углу)

        az_bins = max(1, int(round(min_sep_deg / az_step)))
        el_bins = max(1, int(round(min_sep_deg / el_step)))
        window_size = (2 * el_bins + 1, 2 * az_bins + 1)

        logger.debug(
            "Шаг сетки: аз=%.2f°, эл=%.2f° → окно локального поиска=%s",
            az_step,
            el_step,
            window_size,
        )

        # Локальные максимумы (по окну)
        local_max = maximum_filter(spectrum, size=window_size, mode="nearest")

        # --- Пик и шум ---
        peak_val = np.max(spectrum)

        if spectrum.size > 200:
            # Берём все значения, сортируем по убыванию,
            # первые ~100 считаем "верхушкой", остальное — фон
            sorted_flat = np.sort(spectrum.ravel())[::-1]
            noise_floor = np.median(sorted_flat[100:])
        else:
            noise_floor = np.min(spectrum)

        # --- PNR (peak-to-noise ratio) ---
        eps = 1e-12
        peak_to_noise_lin = (peak_val + eps) / (noise_floor + eps)
        peak_to_noise_db = 10.0 * np.log10(peak_to_noise_lin)

        logger.info(
            "MUSIC: пик=%.3e, шум≈%.3e, PNR≈%.1f dB",
            peak_val, noise_floor, peak_to_noise_db
        )

        # 1) Грубый детектор "есть сигнал / нет сигнала"
        if peak_to_noise_db < self.min_peak_to_noise_db:
            logger.info(
                "MUSIC: пик слишком слабый (PNR=%.1f dB < %.1f dB) — считаем, что сигнала нет",
                peak_to_noise_db, self.min_peak_to_noise_db
            )
            return [(self.no_signal_az, self.no_signal_el)]

        # 2) Порог для локальных максимумов относительно главного пика
        local_peak_factor = 10.0 ** (-self.local_peak_rel_db / 10.0)
        threshold = peak_val * local_peak_factor

        logger.debug(
            "MUSIC: порог локальных пиков=%.3e (%.1f dB ниже пика)",
            threshold,
            self.local_peak_rel_db,
        )


        # --- Поиск локальных максимумов выше порога ---
        peaks = (spectrum == local_max) & (spectrum > threshold)
        peak_coords = np.argwhere(peaks)

        logger.info("Найдено пиков выше порога: %d", len(peak_coords))

        if len(peak_coords) == 0:
            logger.warning(
                "MUSIC: нет локальных максимумов выше порога (PNR=%.1f dB) — считаем, что сигнала нет",
                peak_to_noise_db,
            )
            return [(self.no_signal_az, self.no_signal_el)]

        values = spectrum[peak_coords[:, 0], peak_coords[:, 1]]
        order = np.argsort(-values)
        peak_coords = peak_coords[order]
        values = values[order]


        # --- 5. Финальный отбор по минимальному расстоянию ---

        def angular_distance(
            az1: float, el1: float, az2: float, el2: float
        ) -> float:
            daz = min(abs(az1 - az2), 360 - abs(az1 - az2))
            return float(np.hypot(daz, el1 - el2))

        selected_az_el: List[Tuple[float, float]] = []
        selected_values: List[float] = []

        min_sep_deg = 4.0

        if self.diag_log and len(peak_coords) > 0:
            show_n = min(10, len(peak_coords))
            lines = []
            lines.append("")
            lines.append(f"Кандидаты направлений (первые {show_n}):")
            lines.append("  # |   Az, ° |   El, ° |      Power |  Power, dB")
            lines.append("----+--------+--------+-----------+-----------")

            for idx, (el_idx, az_idx) in enumerate(peak_coords[:show_n]):
                az = float(az_scan[az_idx])
                el = float(el_scan[el_idx])
                val = float(values[idx])
                val_db = 10 * np.log10(val + 1e-20)

                lines.append(
                    f"{idx+1:3d} | {az:7.1f} | {el:7.1f} | {val:10.3e} | {val_db:10.2f}"
                )

            logger.debug("\n".join(lines))


        for (el_idx, az_idx), val in zip(peak_coords, values):
            az = float(az_scan[az_idx])
            el = float(el_scan[el_idx])

            if not selected_az_el:
                selected_az_el.append((az, el))
                selected_values.append(float(val))
                logger.info(
                    "Принято направление #%d: азимут=%.1f°, угол места=%.1f° (%.1f дБ)",
                    len(selected_az_el),
                    az,
                    el,
                    10 * np.log10(val + 1e-20),
                )
            else:
                too_close = any(
                    angular_distance(az, el, az0, el0) < min_sep_deg
                    for az0, el0 in selected_az_el
                )
                if not too_close:
                    selected_az_el.append((az, el))
                    selected_values.append(float(val))
                    logger.info(
                        "Принято направление #%d: азимут=%.1f°, угол места=%.1f° (%.1f дБ)",
                        len(selected_az_el),
                        az,
                        el,
                        10 * np.log10(val + 1e-20),
                    )

            if len(selected_az_el) >= max(self.num_signals, 1):
                break

        if not selected_az_el:
            logger.warning(
                "После фильтрации по минимальному расстоянию не осталось направлений"
            )

        logger.info("ИТОГО: обнаружено направлений: %d", len(selected_az_el))

        if len(selected_az_el) > 0:
            lines = []
            lines.append("")
            lines.append("Финально принятые направления:")
            lines.append("  # |   Az, ° |   El, ° |  Power, dB (относ.)")
            lines.append("----+--------+--------+---------------------")

            # Нормируем мощности относительно максимальной принятой
            max_sel_val = max(selected_values) if selected_values else 1.0

            for i, ((az, el), val) in enumerate(
                zip(selected_az_el, selected_values), start=1
            ):
                rel_db = 10 * np.log10(val / max_sel_val + 1e-20)
                lines.append(
                    f"{i:3d} | {az-90:7.1f} | {el:7.1f} | {rel_db:9.2f}"
                )

            logger.info("\n".join(lines))
        else:
            logger.warning(
                "После фильтрации по минимальному расстоянию не осталось направлений"
            )


        return selected_az_el

    # ------------------------------------------------------------------ #
    #                     Пространственное сглаживание                   #
    # ------------------------------------------------------------------ #

    def _spatial_smoothing(self, R: np.ndarray, subarray_size: int) -> np.ndarray:
        """
        Пространственное сглаживание (forward, с максимальным перекрытием).

        Parameters
        ----------
        R : np.ndarray
            Ковариационная матрица (M, M).
        subarray_size : int
            Размер подмассива (например, 4 при 5 элементах).

        Returns
        -------
        np.ndarray
            Сглаженная ковариационная матрица.
        """
        M = R.shape[0]
        if subarray_size >= M or subarray_size < 2:
            return R

        num_subarrays = M - subarray_size + 1
        if num_subarrays <= 0:
            return R

        Rss = np.zeros_like(R, dtype=np.complex128)
        for i in range(num_subarrays):
            sub = R[i : i + subarray_size, i : i + subarray_size]
            Rss += sub

        Rss /= num_subarrays
        return Rss
