import numpy as np
from numpy.linalg import svd

from scipy.constants import speed_of_light
from scipy.ndimage import maximum_filter
import scipy.signal
from scipy.signal import find_peaks
from numba import float32, njit, vectorize

class SensorArray:
    def __init__(self, element_positions):
        """
        Инициализация класса с произвольными позициями элементов антенны.

        element_positions: ndarray формы (3, N), где
            3 - координаты (x, y, z),
            N - количество элементов.
        """
        self.element_positions = element_positions
        self.num_elements = element_positions.shape[1]

    def get_element_positions(self):
        """
        Возвращает позиции элементов антенны.
        """
        return self.element_positions

    def get_steering_vector(self, azimuth, elevation, fc):
        """
        Вычисление вектора направленности (steering vector) для заданных азимута и угла возвышения.

        azimuth: азимут в градусах
        elevation: угол возвышения в градусах
        fc: частота сигнала в Гц
        """
        # Преобразование углов в радианы
        azimuth_rad = np.deg2rad(azimuth)
        elevation_rad = np.deg2rad(elevation)

        # Вычисление длины волны
        wavelength = speed_of_light / fc

        # Вектор направленности для каждого элемента
        steering_vector = np.exp(1j * 2 * np.pi / wavelength * (
            self.element_positions[0, :] * np.sin(azimuth_rad) * np.cos(elevation_rad) +
            self.element_positions[1, :] * np.sin(elevation_rad) +
            self.element_positions[2, :] * np.cos(azimuth_rad) * np.cos(elevation_rad)
        ))

        return steering_vector

    def generate_signal(self, Nsamp, angs, noisePwr, fc):
        """
        Генерация сигнала для массива антенн с заданными углами прихода и шумом.

        Nsamp: количество снимков
        angs: углы прихода сигналов (азимут и угол возвышения) формы (2, num_signals)
        noisePwr: мощность шума
        fc: частота сигнала в Гц
        """
        num_signals = angs.shape[1]

        # Инициализация матрицы сигнала
        signal = np.zeros((self.num_elements, Nsamp), dtype=complex)

        for i in range(num_signals):
            az = angs[0, i]
            el = angs[1, i]
            steering = self.get_steering_vector(az, el, fc)

            # Генерация случайного сигнала для каждого угла
            random_signal = np.random.randn(Nsamp) + 1j * np.random.randn(Nsamp)
            signal += np.outer(steering, random_signal)

        # Добавляем шум к сигналу
        noise = np.sqrt(noisePwr / 2) * (np.random.randn(self.num_elements, Nsamp) +
                                         1j * np.random.randn(self.num_elements, Nsamp))
        signal += noise

        return signal

    def resample_signal(self, complex_data, originalFs, targetFs):
        """
        Выполняет ресемплинг сигнала с исходной частотой дискретизации на желаемую.
        Для вектора размером [5,Nsamp]

        :param complex_data: Массив комплексных чисел.
        :param originalFs: Исходная частота дискретизации.
        :param targetFs: Желаемая частота дискретизации.
        :return: Ресемплированный сигнал.
        """

        decimationFactor = originalFs / targetFs  # Понижающий коэффициент

        # Ресемплинг сигнала
        num_samples = int(complex_data.shape[1] / decimationFactor)  # Вычисляем количество выборок
        resampled_signal = scipy.signal.resample(complex_data, num_samples,axis=1)

        return resampled_signal


class MUSIC2D:
    def __init__(self, sensor_array, fc, azimuth_scan, elevation_scan, num_signals):
        """
        Инициализация класса для 2D MUSIC.

        sensor_array: объект класса SensorArray, задающий антенную решетку.
        fc: частота сигнала в Гц.
        """
        self.sensor_array = sensor_array
        self.fc = fc
        self.wavelength = 3e8 / fc  # длина волны
        self.num_signal = 1
        self.azimuth_scan = azimuth_scan
        self.elevation_scan = elevation_scan
        self.steering_vectors = None  # Управляющие векторы для всех углов
        self.precompute_steering_vectors()
        self.num_signals = num_signals

    def precompute_steering_vectors(self):
        """
        Предвычисление управляющих векторов для всех комбинаций азимутальных и возвышенческих углов.
        """
        azimuth_scan = np.radians(self.azimuth_scan)
        elevation_scan = np.radians(self.elevation_scan)
        az_mesh, el_mesh = np.meshgrid(self.azimuth_scan, self.elevation_scan)
        az_el_pairs = np.stack([az_mesh.ravel(), el_mesh.ravel()], axis=1)

        # Создание управляющих векторов для всех комбинаций углов
        self.steering_vectors = np.array([self.sensor_array.get_steering_vector(az, el, self.fc)
                                          for az, el in az_el_pairs])

        # Восстановление формы для последующих вычислений
        self.steering_vectors = self.steering_vectors.reshape(len(elevation_scan), len(azimuth_scan), -1)

    def estimate_covariance_matrix(self, signal):
        """
        Оценка ковариационной матрицы сигнала.

        signal: матрица сигналов формы (число элементов, число снимков).
        """
        return np.dot(signal, signal.conj().T) / signal.shape[1]

    def perform_svd(self, covariance_matrix):
        """
        Разложение ковариационной матрицы с помощью SVD для получения шумового подпространства.
        """
        U, S, Vh = svd(covariance_matrix)
        threshold = self.adaptive_threshold(S)
        num_signals = np.sum(S > threshold)  # Определяем количество сигналов по числу значительных сингулярных значений
        self.num_signal = num_signals

        noise_subspace = U[:, num_signals:]  # Шумовое подпространство
        return noise_subspace

    def adaptive_threshold(self, S):
        mean_s = np.mean(S)
        std_s = np.std(S)
        threshold = mean_s + 0.7*std_s  # Порог, например, на 2 стандартных отклонения выше среднего
        return threshold

    def adaptive_threshold_music(self,S):
        q1 = np.percentile(S, 25)  # Первый квартиль
        q3 = np.percentile(S, 75)  # Третий квартиль
        iqr = q3 - q1  # Интерквартильный размах
        threshold = q3 + np.std(S) * iqr  # Порог на основе IQR
        return threshold

    def steering_vector(self, azimuth, elevation):
        """
        Вычисление вектора направленности для заданных азимута и угла возвышения.
        """
        azimuth_rad = np.deg2rad(azimuth)
        elevation_rad = np.deg2rad(elevation)

        # Координаты элементов решетки
        element_positions = self.sensor_array.get_element_positions()

        # Вектор направленности
        steering = np.exp(1j * 2 * np.pi / self.wavelength * (
                element_positions[0, :] * np.sin(azimuth_rad) * np.cos(elevation_rad) +
                element_positions[1, :] * np.sin(elevation_rad) +
                element_positions[2, :] * np.cos(azimuth_rad)
        ))

        return steering

    def mvdr_spectrum(self, azimuth_scan, elevation_scan, signal):
        """
        Оценка спектра MUSIC для каждого угла азимута и возвышения.

        azimuth_scan: диапазон углов азимута для поиска (в градусах).
        elevation_scan: диапазон углов возвышения для поиска (в градусах).
        signal: матрица сигналов формы (число элементов, число снимков).
        """
        covariance_matrix = self.estimate_covariance_matrix(signal)
        noise_subspace = self.perform_svd(covariance_matrix)

        spectrum = np.zeros((len(elevation_scan), len(azimuth_scan)))

        for i, el in enumerate(elevation_scan):
            for j, az in enumerate(azimuth_scan):
                steering_vector = self.sensor_array.get_steering_vector(az, el, self.fc)
                steering_vector = steering_vector[:, np.newaxis]

                # Проверка на нулевое значение перед делением
                denominator = np.abs(
                    np.dot(steering_vector.conj().T, np.dot(noise_subspace, noise_subspace.conj().T @ steering_vector))
                )

                # Заменяем на значение, близкое к шуму, если деление на ноль
                if denominator == 0:
                    spectrum[i, j] = np.finfo(float).eps  # Малое значение
                else:
                    spectrum[i, j] = 1 / denominator

        # Сглаживание спектра
        spectrum = self.smooth_spectrum(spectrum)

        return spectrum

    def music_spectrum(self, signal):
        """
        Оценка спектра MUSIC для каждого угла азимута и возвышения с использованием предвычисленных значений.
        """

        covariance_matrix = self.estimate_covariance_matrix(signal)

        # Находим собственные значения и векторы
        eigenvalues, eigenvectors = np.linalg.eig(covariance_matrix)

        threshold = self.adaptive_threshold_music(np.abs(eigenvalues))
        if (self.num_signals == 0) or (self.num_signals > 4):
            self.num_signals = np.sum(np.abs(eigenvalues) > threshold)  # Определяем количество сигналов по числу значительных сингулярных значений

        # Сортируем собственные значения и векторы
        sorted_indices = np.argsort(np.abs(eigenvalues))[::-1]
        eigenvalues = np.abs(eigenvalues[sorted_indices])
        # print(f"eigen: {eigenvalues}")
        noise_subspace = eigenvectors[:, sorted_indices[self.num_signals:]]  # Подпространство шума

        spectrum = np.zeros((len(self.elevation_scan), len(self.azimuth_scan)))

        # Векторизация расчета спектра MUSIC
        max_num = -99999
        max_i = -10
        for i in range(self.steering_vectors.shape[0]):
            for j in range(self.steering_vectors.shape[1]):
                steering_vector = self.steering_vectors[i, j][:, np.newaxis]
                denominator = np.abs(
                    np.dot(steering_vector.conj().T,
                           np.dot(noise_subspace, noise_subspace.conj().T @ steering_vector)))

                spectrum[i, j] = 1 / denominator
                if spectrum[i, j] > max_num :
                    max_i = i

        spectrum[np.isinf(spectrum)] = np.finfo(float).eps

        # Эта строка кода выполняет срез массива и извлекает центральную строку из 2D массива spectrum
        spectrum = spectrum[max_i, :]
        
        return spectrum

    def estimate_doa_old(self, signal):
        """
        Оценка углов прихода (DOA) с использованием 2D MUSIC.
        """
        spectrum = self.music_spectrum(signal)

        # Нахождение локальных максимумов в двумерном спектре
        neighborhood_size = 3  # Размер окна для поиска максимумов
        local_max = (spectrum == maximum_filter(spectrum, size=neighborhood_size))

        # Применение порога (например, для удаления шума)
        threshold = 0.05 * np.max(spectrum)  # Замените на нужный вам порог
        detected_peaks = np.where(local_max & (spectrum > threshold))

        # Извлечение азимутов и углов возвышения для найденных максимумов
        estimated_azimuths = self.azimuth_scan[detected_peaks[1]]
        estimated_elevations = self.elevation_scan[detected_peaks[0]]

        # Возвращаем уникальные углы
        estimated_angles = np.column_stack((estimated_azimuths, estimated_elevations))

        return estimated_angles.tolist()
    
    def estimate_doa_2d(self, signal):
        """
        Оценка углов прихода (DOA) с использованием 2D MUSIC.
        """
        spectrum = self.music_spectrum(signal)  # Получаем 2D MUSIC спектр

        # Нахождение локальных максимумов в двумерном спектре
        peaks, _ = find_peaks(spectrum.flatten(), height=np.mean(spectrum.flatten()))  # Задайте пороговое значение height

        # Сортировка пиков по значению спектра (по убыванию)
        sorted_peaks = np.argsort(spectrum.flatten()[peaks])[::-1]

        # Извлечение индексов первых двух наибольших пиков
        top_peaks = peaks[sorted_peaks[:self.num_signals]]

        # Преобразование плоских индексов обратно в двумерные
        max_indices = np.unravel_index(top_peaks, spectrum.shape)

        # Соответствующие углы азимута и угла возвышения
        estimated_azimuths = self.azimuth_scan[max_indices[1]]
        estimated_elevations = self.elevation_scan[max_indices[0]]

        # if (estimated_azimuths == 55 | estimated_azimuths == 125): estimated_azimuths = 400


        # Объединение углов в пары
        estimated_angles = np.column_stack((estimated_azimuths, estimated_elevations))

        return estimated_angles.tolist()
    
    def estimate_doa_2d_full(self, signal):
        """
        Оценка углов прихода (DOA) с использованием 2D MUSIC.
        """
        spectrum = self.music_spectrum(signal)  # Получаем 2D MUSIC спектр

        sector_start = 0  # начало сектора
        sector_end = 200   # конец сектора

        # Находим минимальное значение в исходных данных
        min_value = np.min(spectrum)
        # Создаем массив из 360 элементов, заполненный минимальным значением
        full_circle = np.full(360, min_value)
        target_indices = np.linspace(sector_start, sector_end, len(spectrum))

        # Округляем до целых индексов и обеспечиваем попадание в диапазон 0-359
        target_indices = np.clip(np.round(target_indices).astype(int), 0, 359)

        # Заполняем соответствующие позиции
        full_circle[target_indices] = spectrum

        return full_circle
    
    def estimate_doa_2d_mean_full(self, signal):
        """
        Оценка углов прихода (DOA) с использованием 2D MUSIC.
        """
        """
        Оценка DOA: усреднение ковариационных матриц по кадрам, затем единичный запуск 2D-MUSIC.
        """
        frames_len=1024
        use_weights=True
        min_energy=1e-9
        M = signal.shape[0]
        num_frames = signal.shape[1] // frames_len
        if num_frames == 0:
            return [], None

        R_acc = np.zeros((M, M), dtype=np.complex128)
        w_sum = 0.0

        for i in range(num_frames):
            frame = signal[:, i * frames_len:(i + 1) * frames_len]

            frame_energy = np.sum(np.abs(frame) ** 2)
            if frame_energy < min_energy:
                continue

            Rk = (frame @ frame.conj().T) / max(frame.shape[1], 1)

            if use_weights:
                wk = frame_energy
            else:
                wk = 1.0

            R_acc += wk * Rk
            w_sum += wk

        if w_sum <= 0:
            return [], None

        R = R_acc / w_sum  # усреднённая ковариация

        # запускаем MUSIC на усреднённой ковариации
        # spectrum = 10 * np.log10(self.music_spectrum_fast(covariance_matrix=R))

        spectrum = self.music_spectrum_fast(covariance_matrix=R)  # Получаем 2D MUSIC спектр

        sector_start = 50  # начало сектора
        sector_end = 200   # конец сектора

        # Находим минимальное значение в исходных данных
        min_value = np.min(spectrum)
        # Создаем массив из 360 элементов, заполненный минимальным значением
        full_circle = np.full(360, min_value)
        target_indices = np.linspace(sector_start, sector_end, len(spectrum))

        # Округляем до целых индексов и обеспечиваем попадание в диапазон 0-359
        target_indices = np.clip(np.round(target_indices).astype(int), 0, 359)

        # Заполняем соответствующие позиции
        full_circle[target_indices] = spectrum

        return full_circle


    "Два метода надо добавить в класс"

    def music_spectrum_fast(self, signal=None, covariance_matrix=None):
        """
        Быстрая оценка MUSIC спектра (векторизованная).
        """
        import time
        from memory_profiler import memory_usage

        start_time = time.time()
        start_memory = memory_usage()[0]

        if covariance_matrix is None:
            if signal is None:
                raise ValueError("Нужно передать либо signal, либо covariance_matrix")
            covariance_matrix = self.estimate_covariance_matrix(signal)

        # Собственные значения/векторы
        eigenvalues, eigenvectors = np.linalg.eig(covariance_matrix)
        threshold = self.adaptive_threshold_music(np.abs(eigenvalues))

        sorted_indices = np.argsort(eigenvalues)[::-1]
        eigenvalues = eigenvalues[sorted_indices]

        if self.num_signals == 0 or self.num_signals > 4:
            self.num_signals = np.sum(np.abs(eigenvalues) > threshold)

        noise_subspace = eigenvectors[:, sorted_indices[self.num_signals:]]  # (M, M-d)

        # === Векторизация MUSIC ===
        # steering_vectors: (Ne, Na, M)
        sv = self.steering_vectors.reshape(-1, self.steering_vectors.shape[-1])  # (Ne*Na, M)
        # (En^H a) для всех a сразу
        proj = noise_subspace.conj().T @ sv.T  # (M-d, Ne*Na)
        denom = np.sum(np.abs(proj) ** 2, axis=0)  # (Ne*Na,)

        spectrum = 1.0 / (denom + 1e-12)
        spectrum = spectrum.reshape(self.steering_vectors.shape[0], self.steering_vectors.shape[1])

        spectrum[np.isinf(spectrum)] = np.finfo(float).eps

        end_time = time.time()
        end_memory = memory_usage()[0]
        # print(f"Время: {end_time - start_time:.3f} с, ΔПамять: {end_memory - start_memory:.3f} МБ")

        # Векторизация расчета спектра MUSIC
        max_num = -99999
        max_i = -10
        for i in range(self.steering_vectors.shape[0]):
            for j in range(self.steering_vectors.shape[1]):
                if spectrum[i, j] > max_num :
                    max_i = i

        spectrum[np.isinf(spectrum)] = np.finfo(float).eps

        # Эта строка кода выполняет срез массива и извлекает центральную строку из 2D массива spectrum
        spectrum = spectrum[max_i, :]

        return spectrum


    def estimate_doa_mean(self, signal, fs=2.5e6, frames_len=10240, use_weights=True, min_energy=1e-9):
        """
        Оценка DOA: усреднение ковариационных матриц по кадрам, затем единичный запуск 2D-MUSIC.
        """
        M = signal.shape[0]
        num_frames = signal.shape[1] // frames_len
        if num_frames == 0:
            return [], None

        R_acc = np.zeros((M, M), dtype=np.complex128)
        w_sum = 0.0

        for i in range(num_frames):
            frame = signal[:, i * frames_len:(i + 1) * frames_len]

            frame_energy = np.sum(np.abs(frame) ** 2)
            if frame_energy < min_energy:
                continue

            Rk = (frame @ frame.conj().T) / max(frame.shape[1], 1)

            if use_weights:
                wk = frame_energy
            else:
                wk = 1.0

            R_acc += wk * Rk
            w_sum += wk

        if w_sum <= 0:
            return [], None

        R = R_acc / w_sum  # усреднённая ковариация

        # запускаем MUSIC на усреднённой ковариации
        spectrum = 10 * np.log10(self.music_spectrum_fast(covariance_matrix=R))

        flat = spectrum.ravel()
        peaks, _ = find_peaks(flat, height=np.mean(flat))
        if peaks.size == 0:
            return [], spectrum

        top = peaks[np.argsort(flat[peaks])[::-1][:self.num_signals]]
        row_idx, col_idx = np.unravel_index(top, spectrum.shape)

        az_est = np.array(self.azimuth_scan)[col_idx]
        el_est = np.array(self.elevation_scan)[row_idx]

        detected = np.column_stack((az_est, el_est)).tolist()

        return detected, spectrum
    
    def music_spectrum_fast(self, signal=None, covariance_matrix=None):
        """
        Быстрая оценка MUSIC спектра (векторизованная).
        """
        # import time
        # from memory_profiler import memory_usage

        # start_time = time.time()
        # start_memory = memory_usage()[0]

        if covariance_matrix is None:
            if signal is None:
                raise ValueError("Нужно передать либо signal, либо covariance_matrix")
            covariance_matrix = self.estimate_covariance_matrix(signal)

        # Собственные значения/векторы
        eigenvalues, eigenvectors = np.linalg.eig(covariance_matrix)
        threshold = self.adaptive_threshold_music(np.abs(eigenvalues))

        sorted_indices = np.argsort(eigenvalues)[::-1]
        eigenvalues = eigenvalues[sorted_indices]

        if self.num_signals == 0 or self.num_signals > 4:
            self.num_signals = np.sum(np.abs(eigenvalues) > threshold)

        noise_subspace = eigenvectors[:, sorted_indices[self.num_signals:]]  # (M, M-d)

        # === Векторизация MUSIC ===
        # steering_vectors: (Ne, Na, M)
        sv = self.steering_vectors.reshape(-1, self.steering_vectors.shape[-1])  # (Ne*Na, M)
        # (En^H a) для всех a сразу
        proj = noise_subspace.conj().T @ sv.T  # (M-d, Ne*Na)
        denom = np.sum(np.abs(proj) ** 2, axis=0)  # (Ne*Na,)

        spectrum = 1.0 / (denom + 1e-12)
        spectrum = spectrum.reshape(self.steering_vectors.shape[0], self.steering_vectors.shape[1])

        spectrum[np.isinf(spectrum)] = np.finfo(float).eps

        # end_time = time.time()
        # end_memory = memory_usage()[0]
        # print(f"Время: {end_time - start_time:.3f} с, ΔПамять: {end_memory - start_memory:.3f} МБ")

        return spectrum


    def estimate_doa_mean(self, signal, fs=2.4e6, frames_len=10240, use_weights=True, min_energy=1e-9):
        """
        Оценка DOA методом 2D-MUSIC:
        - усреднение ковариационных матриц по кадрам
        - поиск пиков по 2D спектру
        """
        M = signal.shape[0]
        num_frames = signal.shape[1] // frames_len
        if num_frames == 0:
            return [], None

        # --- 1. Накопление ковариации ---
        R_acc = np.zeros((M, M), dtype=np.complex128)
        w_sum = 0.0

        for i in range(num_frames):
            frame = signal[:, i * frames_len:(i + 1) * frames_len]
            frame_energy = np.sum(np.abs(frame) ** 2)
            if frame_energy < min_energy:
                continue

            Rk = (frame @ frame.conj().T) / max(frame.shape[1], 1)
            wk = frame_energy if use_weights else 1.0

            R_acc += wk * Rk
            w_sum += wk

        if w_sum <= 0:
            return [], None

        # Усреднённая ковариация
        R = R_acc / w_sum

        # --- 2. MUSIC спектр ---
        spectrum = 10 * np.log10(self.music_spectrum_fast(covariance_matrix=R))

        # --- 3. Поиск 2D пиков с фильтром по min_sep_deg ---
        az_scan = np.asarray(self.azimuth_scan, dtype=float)
        el_scan = np.asarray(self.elevation_scan, dtype=float)
        min_sep_deg = 10.0

        # шаги сетки
        az_step = np.median(np.diff(az_scan)) if az_scan.size > 1 else 1.0
        el_step = np.median(np.diff(el_scan)) if el_scan.size > 1 else 1.0

        # размер окна для фильтра максимума
        az_bins = max(1, int(round(min_sep_deg / max(az_step, 1e-12))))
        el_bins = max(1, int(round(min_sep_deg / max(el_step, 1e-12))))
        win = (2 * el_bins + 1, 2 * az_bins + 1)

        # локальные максимумы
        maxf = maximum_filter(spectrum, size=win, mode='nearest')
        peaks_mask = (spectrum == maxf)
        thr = np.mean(spectrum)
        peaks_mask &= (spectrum >= thr)

        coords = np.argwhere(peaks_mask)  # (row_idx=el, col_idx=az)
        if coords.size == 0:
            return [], spectrum

        vals = spectrum[coords[:, 0], coords[:, 1]]
        order = np.argsort(-vals)
        coords = coords[order]

        def ang_diff_deg(a, b):
            return abs((a - b + 180.0) % 360.0 - 180.0)

        selected = []
        for r, c in coords:
            az = float(az_scan[c])
            el = float(el_scan[r])

            if not selected:
                selected.append((az, el))
            else:
                dists = [np.hypot(ang_diff_deg(az, az0), abs(el - el0)) for az0, el0 in selected]
                if np.min(dists) < min_sep_deg:
                    continue

                selected.append((az, el))

            if len(selected) >= self.num_signals:
                break

        detected = selected
        return detected, spectrum