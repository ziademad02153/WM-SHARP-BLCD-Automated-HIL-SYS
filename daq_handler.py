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
                
                # 1. Process Motor_RPM (data[0] is ai0 Square Wave Pulse Train)
                motor_wave = data[0]
                crossings = 0
                for i in range(1, len(motor_wave)):
                    if motor_wave[i-1] < 2.5 and motor_wave[i] >= 2.5:
                        crossings += 1
                
                # Frequency (Hz) = crossings / 0.1 seconds
                frequency = crossings / 0.1
                
                # Formula derived from LabVIEW specs: 40 Hz = 800 RPM
                rpm = frequency * 20.0
                processed_data.append(rpm)
                
                # 2. Process Analog Channels (ai1 to ai7 DC Voltage)
                for ch_idx in range(1, 8):
                    avg_val = sum(data[ch_idx]) / 100.0
                    processed_data.append(avg_val)
                    
                self.data_ready.emit(processed_data)
                
            except Exception as e:
                if self.running:
                    self.stop()
                    self.error_occurred.emit(f"🔴 HARDWARE DISCONNECTED: {e}")
                break
