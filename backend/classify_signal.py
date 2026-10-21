import numpy as np
import scipy.io
import onnxruntime as ort  # Импортируем необходимую библиотеку для работы с ONNX
import scipy.signal

# Загрузка модели
class classify_signal:
    def __init__(self, ONNX_model_path, class_labels):
        """
        Инициализация класса.

        :param ONNX_model_path: Путь к файлу модели ONNX.
        :param class_labels: Список меток классов.
        """
        self.model = ort.InferenceSession(ONNX_model_path)  # Загружаем модель
        self.class_labels = class_labels  # Сохраняем метки классов
        self.min_length = 1024  # Минимальная длина данных

    def split_complex_to_real_imag(self, complex_data):
        """
        Разделяет комплексные данные на действительную и мнимую части.

        :param complex_data: Массив комплексных чисел.
        :return: Массив с действительной и мнимой частями.
        """
        real_part = np.real(complex_data)  # Получаем действительную часть
        imag_part = np.imag(complex_data)  # Получаем мнимую часть
        output_data = np.stack((real_part, imag_part), axis=-1)  # Сохраняем в выходной массив
        return output_data

    def prepare_data(self, complex_data):
        """
        Подготавливает данные для модели.

        :param complex_data: Массив комплексных чисел.
        :return: Подготовленный массив данных для классификации.
        """
        # Разделяем комплексные данные
        prepared_data = self.split_complex_to_real_imag(complex_data)

        # Проверяем и добавляем нули для достижения минимальной длины
        if prepared_data.shape[0] < self.min_length:
            padding = np.zeros((self.min_length - prepared_data.shape[0], 2))  # Создаем нулевую матрицу для заполнения
            prepared_data = np.vstack((prepared_data, padding))  # Объединяем с подготовленными данными

        # Отбрасываем лишние данные, если они есть
        prepared_data = prepared_data[:self.min_length, :, :]  # Убедитесь, что размерность соответствует модели

        # Приведение типа данных к float32
        prepared_data = prepared_data.astype(np.float32)

        # Нормализация данных (раскомментируйте и настройте, если нужно)
        # mean = np.array([0.0, 0.0], dtype=np.float32)  # Замените на фактические значения
        # std = np.array([1.0, 1.0], dtype=np.float32)  # Замените на фактические значения
        # prepared_data = (prepared_data - mean) / std

        return prepared_data  # Возвращаем подготовленные данные

    def classify_signal(self, input_data):
        """
        Классифицирует сигнал, используя загруженную модель.

        :param input_data: Данные для классификации. Вектор комплексных значений
        :return: Вероятности классов.
        """

        input_name = self.model.get_inputs()[0].name  # Получаем имя входного слоя
        output_name = self.model.get_outputs()[0].name  # Получаем имя выходного слоя

        # Подготовка данных
        prepared_data = self.prepare_data(input_data)  # Изменено на input_data

        # Выполняем инференс
        probabilities = self.model.run([output_name], {input_name: prepared_data})[0]

        # Получаем индексы класса с максимальной вероятностью
        predicted_class_idx = np.argmax(probabilities)  # Находим индекс класса с максимальной вероятностью

        # Выводим метку класса
        predicted_label = self.class_labels[predicted_class_idx]  # Получаем метку класса

        return probabilities  # Возвращаем вероятности классов

    def normalize_signal(self, complex_data):
        """
        Нормализует сигнал по амплитуде.

        :param complex_data: Массив комплексных чисел.
        :return: Нормализованный сигнал.
        """
        max_val = np.max(np.abs(complex_data))  # Находим максимальную амплитуду
        normalized_signal = complex_data / max_val  # Нормализуем сигнал

        return normalized_signal

    def resample_signal(self, complex_data, originalFs, targetFs):
        """
        Выполняет ресемплинг сигнала с исходной частотой дискретизации на желаемую.

        :param complex_data: Массив комплексных чисел.
        :param originalFs: Исходная частота дискретизации.
        :param targetFs: Желаемая частота дискретизации.
        :return: Ресемплированный сигнал.
        """
        normalized_signal = self.normalize_signal(complex_data)  # Нормализуем сигнал
        decimationFactor = originalFs / targetFs  # Понижающий коэффициент

        # Ресемплинг сигнала
        num_samples = int(len(normalized_signal) / decimationFactor)  # Вычисляем количество выборок
        resampled_signal = scipy.signal.resample(normalized_signal, num_samples)

        return resampled_signal
