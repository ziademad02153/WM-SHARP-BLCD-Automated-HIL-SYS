import nidaqmx
from PyQt5.QtCore import QObject, pyqtSignal, QTimer

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
        # 7 Channels:
        # AI0=Cold_V, AI1=Hot_V, AI2=Pump, AI3=Softener,
        # AI4=GearMotor, AI5=Motor_RPM, AI6=Door
        self.channels = [
            'Dev1/ai0', 'Dev1/ai1', 'Dev1/ai2',
            'Dev1/ai3', 'Dev1/ai4', 'Dev1/ai5', 'Dev1/ai6'
        ]

    def start(self):
        self.running = True
        self.ticks = 0
        if not self.simulate:
            try:
                self.task = nidaqmx.Task()
                for ch in self.channels:
                    self.task.ai_channels.add_ai_voltage_chan(ch)
                self.timer.start(100)  # 10Hz
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
        if not self.running:
            return

        self.ticks += 1

        if self.simulate:
            # Format: [Cold_V, Hot_V, Softener, Pump, GearMotor, Motor_RPM, Door]
            if self.ticks <= 200:
                # 1. Water Fill (0s-20s): Cold valve ON, RPM=0
                data = [5.0, 0.0, 0.0, 0.0, 0.0, 0.0, 5.0]
            elif self.ticks <= 500:
                # 2. Wash (20s-50s): BLDC running ~300RPM, relays off
                rpm_sim = 1.5  # Simulated voltage representing ~300 RPM
                data = [0.0, 0.0, 0.0, 0.0, 0.0, rpm_sim, 5.0]
            elif self.ticks <= 560:
                # 3. Drain (50s-56s): Pump ON (index 3)
                data = [0.0, 0.0, 0.0, 5.0, 0.0, 0.5, 5.0]
            elif self.ticks <= 800:
                # 4. Spin (56s-80s): GearMotor ON, RPM rising to max ~700
                spin_progress = min((self.ticks - 560) / 240, 1.0)
                rpm_sim = spin_progress * 3.5  # Simulated voltage representing 0-700 RPM
                data = [0.0, 0.0, 0.0, 0.0, 5.0, rpm_sim, 5.0]
            else:
                # 5. End / Idle
                data = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 5.0]
        else:
            try:
                data = self.task.read()
                if not isinstance(data, list):
                    data = [data] * 7
            except Exception as e:
                self.error_occurred.emit(f"🔴 HARDWARE CRITICAL ERROR: {e}")
                data = [0.0] * 7

        self.data_ready.emit(data)
