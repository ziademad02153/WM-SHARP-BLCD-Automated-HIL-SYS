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
            
            # 10,000 Hz Industrial Sampling Rate (Matches LabVIEW High-Speed standard)
            self.task.timing.cfg_samp_clk_timing(
                rate=10000.0,
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
                # Read 1000 samples (takes exactly 0.1 seconds at 10,000 Hz)
                data = self.task.read(number_of_samples_per_channel=1000, timeout=1.0)
                
                if not isinstance(data[0], list):
                    continue

                processed_data = []
                
                # 1. Process Motor_RPM using a rolling 0.25-second buffer (2500 samples)
                if not hasattr(self, 'motor_buffer'):
                    self.motor_buffer = []
                
                self.motor_buffer.extend(data[0])
                if len(self.motor_buffer) > 2500:
                    self.motor_buffer = self.motor_buffer[-2500:]
                
                crossing_indices = []
                if not hasattr(self, 'last_crossing_state'):
                    self.last_crossing_state = 'DOWN'
                
                # --- FINE-TUNED CALIBRATION: Pulley Ratio 3.14 ---
                PULSES_PER_REV = 12.0
                PULLEY_RATIO = 3.14 # Adjusted to perfectly align 255 raw motor RPM to 800 Tub RPM
                
                # Enhanced sensitivity: 2.0V/1.0V to capture higher-frequency, lower-amplitude pulses
                for i in range(len(self.motor_buffer)):
                    val = self.motor_buffer[i]
                    if self.last_crossing_state == 'DOWN' and val >= 2.0:
                        self.last_crossing_state = 'UP'
                        crossing_indices.append(i)
                    elif self.last_crossing_state == 'UP' and val <= 1.0:
                        self.last_crossing_state = 'DOWN'
                
                if len(crossing_indices) >= 2:
                    num_periods = len(crossing_indices) - 1
                    time_elapsed = (crossing_indices[-1] - crossing_indices[0]) / 10000.0
                    frequency = num_periods / time_elapsed
                    motor_rpm = (frequency * 60.0) / PULSES_PER_REV
                    rpm = motor_rpm * PULLEY_RATIO
                else:
                    rpm = 0.0
                
                # --- DSP NOISE REJECTION FILTER ---
                # Detect and reject electromagnetic noise spikes (e.g., >1500 RPM transient jumps)
                if not hasattr(self, 'last_valid_rpm'):
                    self.last_valid_rpm = 0.0
                
                # Slew-rate limit: Motor cannot physically jump by >500 RPM in 0.1 seconds from a low speed
                # This completely ignores single-point electromagnetic spikes (2000 RPM) while allowing smooth acceleration
                if abs(rpm - self.last_valid_rpm) > 500.0 and self.last_valid_rpm < 1000.0:
                    rpm = self.last_valid_rpm
                else:
                    if rpm > 2600.0:  # Absolute physical ceiling for 800 RPM tub speed
                        rpm = self.last_valid_rpm
                    else:
                        self.last_valid_rpm = rpm
                
                # --- LABVIEW-GRADE MEDIAN FILTER (Size 3) ---
                if not hasattr(self, 'rpm_history'):
                    self.rpm_history = [0.0, 0.0, 0.0]
                
                self.rpm_history.append(rpm)
                if len(self.rpm_history) > 3:
                    self.rpm_history.pop(0)
                    
                sorted_history = sorted(self.rpm_history)
                filtered_rpm = sorted_history[1]
                
                processed_data.append(round(filtered_rpm, 2)) 

                
                # 2. Process Analog Channels (ai1 to ai7 DC Voltage)
                for ch_idx in range(1, 8):
                    avg_val = sum(data[ch_idx]) / 1000.0
                    processed_data.append(round(avg_val, 3)) 
                    
                self.data_ready.emit(processed_data)
                
            except Exception as e:
                if self.running:
                    self.stop()
                    self.error_occurred.emit(f"🔴 HARDWARE DISCONNECTED: {e}")
                break
