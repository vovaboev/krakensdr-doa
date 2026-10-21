from receiver.iq_header import IQHeader
from receiver.kraken_sdr_receiver import ReceiverRTLSDR
import queue
import time

from scipy import fft, signal
import numpy as np

data_que = queue.Queue(1)
receiver = ReceiverRTLSDR(data_que, "eth", "192.168.0.113")
first_frame = 1
channel_number = 0
spectrum_window_size = fft.next_fast_len(4096)
spectrum = None
dsp_decimation = 1

data_ready = False

while True:
    get_iq_failed = receiver.get_iq_online()
    start_time = time.time()
    #self.save_processing_status()

    #que_data_packet.append(["iq_header", self.module_receiver.iq_header])
    #self.logger.debug("IQ header has been put into the data que entity")

    # Check frame type for processing
    """
        You can enable here to process other frame types (such as call type frames)
    """
    en_proc = (
        receiver.iq_header.frame_type == receiver.iq_header.FRAME_TYPE_DATA
    )  # or \
    # (self.module_receiver.iq_header.frame_type == self.module_receiver.iq_header.FRAME_TYPE_CAL)# For debug purposes

    data_ready = False
    if en_proc:
        if receiver.iq_samples.size and not get_iq_failed:
            processed_signal = np.ascontiguousarray(receiver.iq_samples)
            sampling_freq = receiver.iq_header.sampling_freq

            print(f"Sampling freq: {sampling_freq}")
            print(f"Received: {processed_signal.shape}")

            #np.savetxt("signal.txt", processed_signal,fmt='%.3f')
            