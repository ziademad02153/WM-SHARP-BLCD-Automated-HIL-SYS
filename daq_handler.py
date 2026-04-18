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
                # Perfect Weight Detection Pattern
                cycle_tick = (self.ticks - 1) % 18
                if cycle_tick < 9:
                    ccw_val = 5.0 if cycle_tick < 3 else 0.0
                    cw_val = 0.0
                else:
                    cw_val = 5.0 if (cycle_tick - 9) < 3 else 0.0
                    ccw_val = 0.0
                
                data = [
                    0.0, # Cold_V
                    0.0, # Hot_V
                    0.0, # Pump
                    0.0, # Clutch
                    cw_val, # Motor_CW
                    ccw_val, # Motor_CCW
                    5.0, # Door (usually 5V/Closed)
                    0.0  # Buzzer
                ]
            else:
                # Baseline for normal testing
                pump_val = 5.0 if self.ticks > 100 else random.choices([0.0, 5.0], weights=[0.9, 0.1])[0]
                
                data = [
                    random.uniform(0, 5), # Cold_V
                    0.0, # Hot_V
                    pump_val, # Pump (Hangs permanently ON after 10s to force E1 test)
                    0.0, # Clutch
                    random.choices([0.0, 5.0], weights=[0.8, 0.2])[0], # Motor_CW
                    random.choices([0.0, 5.0], weights=[0.8, 0.2])[0], # Motor_CCW
                    random.choices([0.0, 5.0], weights=[0.1, 0.9])[0], # Door 
                    random.choices([0.0, 5.0], weights=[0.95, 0.05])[0]  # Buzzer
                ]
        else:
            try:
                data = self.task.read()
                if not isinstance(data, list):
                    data = [data] * 8
            except Exception as e:
                self.error_occurred.emit(f"Read Error: {e}")
                data = [0.0]*8
        
        self.data_ready.emit(data)
