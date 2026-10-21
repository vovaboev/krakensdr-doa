import numpy as np
from doa_2d_music import MUSIC2D, SensorArray
from classify_signal import classify_signal

def main():

    # чтение данных
    #  путь к файлу с сигналом
    file_path = 'signal.txt'

    # Чтение данных из файла и преобразование в массив NumPy
    data = np.genfromtxt(file_path, dtype=complex, max_rows=5)
    data = data.reshape(5, 1048576)

    # Константы
    fc = 700e6  # Рабочая частота (Гц)
    originalFs = 2.5e6  # Исходная частота дискретизации (2,5 МГц)
    targetFs = 40e4  # Желаемая частота дискретизации (400 кГц)
    Nsamp = 1024*10  # Количество отсчетов

    complex_data = data[:5, :Nsamp]

    # Позиции элементов антенны (здесь используется пример Крест Милса)
    x_a = np.array([0, 0, 0, 0, 0])
    y_a = np.array([-0.16, 0, 0.16, 0, 0])
    z_a = np.array([0, 0, 0, -0.2, 0.2])

    # Задание позиций элементов в виде массива (x, y, z)
    element_positions = np.vstack([x_a, y_a, z_a])

    # Создаем объект массива антенн
    sensor_array = SensorArray(element_positions)

    # Ресемплинг сигнала
    signal_sCA = sensor_array.resample_signal(complex_data, originalFs, targetFs)

    # Диапазоны для поиска DOA
    azimuth_scan = np.linspace(55, 125, 100)  # Азимут
    elevation_scan = np.linspace(-25, 25, 100)  # Возвышение

    # Создаем объект MUSIC 2D
    music_estimator = MUSIC2D(sensor_array, fc, azimuth_scan, elevation_scan)

    # Оценка углов прихода (DOA)
    estimated_angles = music_estimator.estimate_doa(signal_sCA)
    print(f"Оцененные углы: {estimated_angles}")

    # Определяем метки классов
    class_labels = [
        '2G', '5G', 'AM_Radio', 'Bluetooth', 'DECT',
        'DVB_T2', 'EDGE', 'FM_Radio', 'GPS', 'GSM',
        'LTE', 'LoRa', 'NB_IoT', 'Satellite_Communication',
        'TETRA', 'WiMax', 'Wi_Fi', 'ZigBee'
    ]

    # Загружаем модель и создаем экземпляр класса этот
    model_path = "signalClassificationModel_quantized.onnx"  # путь к модели
    signal_classifier = classify_signal(model_path, class_labels)

    # Классификация сигнала
    probabilities = signal_classifier.classify_signal(signal_sCA[:1, :].T)
    print(f"Вероятности классов: {probabilities}")

    # Получаем индексы топ-3 классов по убыванию вероятности
    top_n = 3
    top_n_indices = np.argsort(probabilities.flatten())[-top_n:][::-1]  # Сортировка по убыванию и выбор top_n индексов

    # Получаем метки топ-3 классов и их вероятности
    top_n_labels = [class_labels[i] for i in top_n_indices]  # Метки классов по индексам
    top_n_probabilities = probabilities.flatten()[top_n_indices]  # Соответствующие вероятности

    # Выводим топ-3 классов с вероятностями
    print(f"Топ-{top_n} классов:")
    for i in range(top_n):
        print(f"Класс: {top_n_labels[i]}, Вероятность: {top_n_probabilities[i]:.4f}")

if __name__ == "__main__":
    main()
