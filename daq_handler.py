import nidaqmx
import nidaqmx.constants
import threading
from PyQt5.QtCore import QObject, pyqtSignal

class DAQHandler(QObject):
    data_ready = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = False
        self.task = None
        self.channels = [
            'cDAQ1Mod1/ai0', 'cDAQ1Mod1/ai1', 'cDAQ1Mod1/ai2', 'cDAQ1Mod1/ai3',
            'cDAQ1Mod1/ai4', 'cDAQ1Mod1/ai5', 'cDAQ1Mod1/ai6', 'cDAQ1Mod1/ai7'
        ]

    def start(self):
        self.running = True
        try:
            self.task = nidaqmx.Task()
            for ch in self.channels:
                self.task.ai_channels.add_ai_voltage_chan(ch)
            
            # Configure hardware timing for 1000 Hz, continuous mode
            self.task.timing.cfg_samp_clk_timing(
                rate=1000.0,
                sample_mode=nidaqmx.constants.AcquisitionType.CONTINUOUS
            )
            
            self.thread = threading.Thread(target=self._daq_loop, daemon=True)
            self.thread.start()
        except Exception as e:
            self.error_occurred.emit(f"Hardware Connection Error: {e}. Check USB or DAQ Chassis.")

    def stop(self):
        self.running = False
        if self.task:
            try:
                self.task.stop()
                self.task.close()
            except:
                pass
            self.task = None

    def _daq_loop(self):
        while self.running:
            try:
                # Read 100 samples (takes exactly 0.1 seconds at 1000 Hz hardware timing)
                data = self.task.read(number_of_samples_per_channel=100, timeout=1.0)
                
                # Check structure
                if not isinstance(data[0], list):
                    # Edge case if only 1 channel exists, but we have 8
                    continue

                processed_data = []
                
                # 1. Process Motor_RPM using a rolling 0.5-second buffer (500 samples)
                # This guarantees high-resolution frequency calculation even at low RPMs
                if not hasattr(self, 'motor_buffer'):
                    self.motor_buffer = []
                
                self.motor_buffer.extend(data[0])
                if len(self.motor_buffer) > 500:
                    self.motor_buffer = self.motor_buffer[-500:]
                
                crossing_indices = []
                if not hasattr(self, 'last_crossing_state'):
                    self.last_crossing_state = 'DOWN' # Initial state
                
                # Hysteresis thresholds: UP at 3.0V, DOWN at 2.0V to avoid noise jitter
                for i in range(len(self.motor_buffer)):
                    val = self.motor_buffer[i]
                    if self.last_crossing_state == 'DOWN' and val >= 3.0:
                        self.last_crossing_state = 'UP'
                        crossing_indices.append(i)
                    elif self.last_crossing_state == 'UP' and val <= 2.0:
                        self.last_crossing_state = 'DOWN'
                
                if len(crossing_indices) >= 2:
                    # Calculate exact time between the first and last crossing in the buffer
                    num_periods = len(crossing_indices) - 1
                    time_elapsed = (crossing_indices[-1] - crossing_indices[0]) / 1000.0
                    frequency = num_periods / time_elapsed
                else:
                    frequency = 0.0
                
                # Washing machine tachometers typically output 6 pulses per revolution.
                # RPM = (Frequency * 60) / 6 = Frequency * 10.0
                rpm = frequency * 10.0
                processed_data.append(round(rpm, 3))  # Round to 3 decimal places
                
                # 2. Process Analog Channels (ai1 to ai7 DC Voltage)
                for ch_idx in range(1, 8):
                    avg_val = sum(data[ch_idx]) / 100.0
                    processed_data.append(round(avg_val, 3))  # Round to 3 decimal places
                    
                self.data_ready.emit(processed_data)
                
            except Exception as e:
                if self.running:
                    self.stop()
                    self.error_occurred.emit(f"🔴 HARDWARE DISCONNECTED: {e}")
                break
