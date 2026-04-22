import nidaqmx
from PyQt5.QtCore import QObject, pyqtSignal, QTimer
import random

class DAQHandler(QObject):
    data_ready = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, simulate=True):
        super().__init__()
        self.simulate = simulate
        self.running = False
        self.ticks = 0
        self.timer = QTimer()
        self.timer.timeout.connect(self.read_data)
        self.task = None
        self.channels = [
            'Dev1/ai0', 'Dev1/ai1', 'Dev1/ai2', 'Dev1/ai3', 
            'Dev1/ai4', 'Dev1/ai5', 'Dev1/ai6', 'Dev1/ai7'
        ]

    def start(self):
        self.running = True
        self.ticks = 0
        if not self.simulate:
            try:
                self.task = nidaqmx.Task()
                for ch in self.channels:
                    self.task.ai_channels.add_ai_voltage_chan(ch)
                self.timer.start(100) # 10Hz
            except Exception as e:
                self.error_occurred.emit(f"DAQ Error: {e}. Falling back to Simulation.")
                self.simulate = True
                self.timer.start(100)
        else:
            self.timer.start(100)

    def stop(self):
        self.running = False
        self.timer.stop()
        if self.task:
            self.task.close()
            self.task = None

    def read_data(self):
        if not self.running: return
        
        self.ticks += 1
        
        if self.simulate:
            if self.ticks <= 72:
                # 1. Weight Detection Pattern (0-7.2s)
                cycle_tick = (self.ticks - 1) % 18
                cw_val = 5.0 if cycle_tick < 3 else 0.0
                ccw_val = 5.0 if 9 <= cycle_tick < 12 else 0.0
                data = [0.0, 0.0, 0.0, 0.0, cw_val, ccw_val, 5.0, 0.0]
            elif self.ticks <= 200:
                # 2. Water Fill Phase (7.2s - 20s)
                data = [5.0, 0.0, 0.0, 0.0, 0.0, 0.0, 5.0, 0.0] # Cold Valve ON
            elif self.ticks <= 500:
                # 3. Wash Phase (20s - 50s)
                cycle_tick = (self.ticks % 20)
                motor_on = 5.0 if cycle_tick < 10 else 0.0
                data = [0.0, 0.0, 0.0, 0.0, motor_on, 0.0, 5.0, 0.0]
            else:
                # 4. End / Idle
                data = [0.0]*8
                data[6] = 5.0 # Door closed
        else:
            try:
                data = self.task.read()
                if not isinstance(data, list):
                    data = [data] * 8
            except Exception as e:
                self.error_occurred.emit(f"🔴 HARDWARE CRITICAL ERROR: {e}")
                # Keep returning zeros to reflect actual loss of signal
                data = [0.0]*8
        
        self.data_ready.emit(data)
