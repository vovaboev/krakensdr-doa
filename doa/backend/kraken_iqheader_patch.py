"""
Расширение класса IQHeader из receiver.iq_header
Ничего не меняем в исходнике Heimdall, просто навешиваем свойства/методы.

Подключение:
    import kraken_iqheader_patch

Важно: импортировать этот модуль до старта воркеров/цикла приёма кадров.
"""

import logging
from receiver.iq_header import IQHeader

log = logging.getLogger("IQHeaderExt")


# ----------------- helpers (станут @property/методами) -----------------

def _is_valid(self):
    """
    Кадр валидный? Проверяем sync_word.
    """
    return self.sync_word == self.SYNC_WORD


def _is_data_frame(self):
    """
    Обычный рабочий кадр с реальными данными.
    """
    return self.frame_type == IQHeader.FRAME_TYPE_DATA


def _is_calibration_frame(self):
    """
    Кадр калибровки (FRAME_TYPE_CAL) — обычно когда Heimdall гоняет noise source.
    DOA/MUSIC на таких кадрах считать не нужно.
    """
    return self.frame_type == IQHeader.FRAME_TYPE_CAL


def _is_dummy_frame(self):
    """
    Dummy-кадр (FRAME_TYPE_DUMMY) — заполнитель.
    """
    return self.frame_type == IQHeader.FRAME_TYPE_DUMMY


def _is_empty_frame(self):
    """
    Пустой кадр (FRAME_TYPE_EMPTY).
    """
    return self.frame_type == IQHeader.FRAME_TYPE_EMPTY


def _sample_sync_ok(self):
    """
    Флаг выравнивания по сэмплам (delay_sync_flag).
    Любое ненулевое значение считаем 'OK'.
    """
    return self.delay_sync_flag != 0


def _iq_sync_ok(self):
    """
    Флаг IQ-калибровки (амплитуда/фаза между каналами).
    Любое ненулевое значение считаем 'OK'.
    """
    return self.iq_sync_flag != 0


def _sync_ok(self):
    """
    Полная синхронизация: и задержка, и IQ в норме.
    """
    return self.sample_sync_ok and self.iq_sync_ok


def _noise_on(self):
    """
    Внутренний noise source включён?
    0 — выкл, !=0 — активен / в управлении FSM.
    """
    return self.noise_source_state != 0


def _can_use_for_music(self):
    """
    Можно ли использовать этот кадр для DOA/MUSIC?

    Условия:
    - корректный sync_word;
    - это data-frame (не CAL, не DUMMY, не EMPTY);
    - оба флага синхронизации в порядке.
    """
    if not self.is_valid:
        return False
    if not self.is_data_frame:
        return False
    if not self.sync_ok:
        return False
    return True


def _log_sync_status(self, logger=None, level=logging.INFO):
    """
    Удобный метод для логов состояния синхронизации.
    """
    lg = logger or log
    frame_idx = getattr(self, "cpi_index", -1)

    msg = (
        f"HDR frame={frame_idx} "
        f"type={self.frame_type} "
        f"valid={self.is_valid} "
        f"delay_sync_flag={self.delay_sync_flag} "
        f"iq_sync_flag={self.iq_sync_flag} "
        f"noise_state={self.noise_source_state} "
        f"sync_ok={self.sync_ok} "
        f"can_use_for_music={self.can_use_for_music}"
    )
    lg.log(level, msg)


# ----------------- навешиваем на IQHeader -----------------

IQHeader.is_valid            = property(_is_valid)
IQHeader.is_data_frame       = property(_is_data_frame)
IQHeader.is_calibration_frame= property(_is_calibration_frame)
IQHeader.is_dummy_frame      = property(_is_dummy_frame)
IQHeader.is_empty_frame      = property(_is_empty_frame)

IQHeader.sample_sync_ok      = property(_sample_sync_ok)
IQHeader.iq_sync_ok          = property(_iq_sync_ok)
IQHeader.sync_ok             = property(_sync_ok)
IQHeader.noise_on            = property(_noise_on)
IQHeader.can_use_for_music   = property(_can_use_for_music)

IQHeader.log_sync_status     = _log_sync_status

log.info("IQHeader monkey-patch: свойства sync_ok/can_use_for_music добавлены")
