import json
import os
from PyQt5.QtCore import QObject, pyqtSignal

class ErrorMonitor(QObject):
    """
    Handles fault detection and error code triggering based on system specifications.
    """
    alarm_triggered = pyqtSignal(str)

    def __init__(self, log_callback, record_callback):
        super().__init__()
        self.log_callback = log_callback
        self.record_callback = record_callback
        self.errors_database = []
        
        # State trackers
        self.pump_timer = 0
        self.continuous_pump_timer = 0
        self.pump_cooldown_timer = 0
        self.motor_fail_timer = 0
        self.water_supply_timer = 0
        self.overflow_timer = 0
        self.motor_stuck_timer = 0
        self.leak_timer = 0
        self.unbalance_retries = 0
        
        # Logging flags
        self.e2_error_logged = False
        self.ea_error_logged = False
        self.thermal_warning_logged = False
        
        self._last_log_time = {}
        self._load_config()

    def _load_config(self):
        spec_path = 'sharp_spec.json'
        if not os.path.exists(spec_path):
            spec_path = 'wm_config.json'
            
        try:
            if os.path.exists(spec_path):
                with open(spec_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.errors_database = config.get("errors", [])
        except Exception:
            pass

    def evaluate_state(self, row_index, state, history):
        """
        Analyzes the current machine state to detect faults.
        """
        phase = state.get('phase', 'IDLE')
        rpm = state.get('rpm', 0)
        pump = state.get('pump_on', False)
        empty = state.get('empty_on', False) 
        cold = state.get('cold_on', False)
        hot = state.get('hot_on', False)
        door_closed = state.get('door_closed', True)
        
        # 1. Lid Opening (E2) - DISABLED UNTIL CONNECTED
        # if row_index > 30 and not door_closed and (phase in ['WASH', 'SPIN', 'WATER_FILL', 'WEIGHT_DETECT'] or phase.startswith('RINSE')):
        #    if pump or rpm > 15 or cold or hot:
        #        if not self.e2_error_logged:
        #            self._trigger("E2", row_index, f"Lid opened during active phase: {phase}")
        #            self.e2_error_logged = True
        # else:
        #    self.e2_error_logged = False

        # 2. Drain Failure (E1) - 15 min limit
        if (phase == 'DRAIN' or pump) and not empty:
            self.pump_timer += 1
            if self.pump_timer == 9000: # 15 min @ 10Hz
                self._trigger("E1", row_index, "Drain timeout: Reset level not reached within 15m")
            
            # Pump Thermal Monitor
            self.continuous_pump_timer += 1
            if self.continuous_pump_timer > 1500: # 150s
                if not self.thermal_warning_logged:
                    msg = "WARNING: Pump continuous operation exceeds 150s thermal limit"
                    self.log_callback(msg)
                    self.record_callback("Pump Duty Cycle", "WARNING", f"Row {row_index}: {msg}")
                    self.thermal_warning_logged = True
        else:
            self.pump_timer = 0
            if not pump:
                self.pump_cooldown_timer += 1
                if self.pump_cooldown_timer >= 100: # 10s
                    self.continuous_pump_timer = 0
                    self.thermal_warning_logged = False
                    self.pump_cooldown_timer = 0
            else:
                self.pump_cooldown_timer = 0
            
        # 3. Water Supply (E5) - 20 min limit
        if phase == 'WATER_FILL' and (cold or hot):
            self.water_supply_timer += 1
            if self.water_supply_timer == 12000:
                self._trigger("E5", row_index, "Fill timeout: Target level not reached within 20m")
        else:
            self.water_supply_timer = 0
            
        # 4. Overflow (E6-1)
        if (cold or hot) and pump:
            self.overflow_timer += 1
            if self.overflow_timer > 100: # Fast detection for safety (10s)
                self._trigger("E6-1", row_index, "Overflow risk: Concurrent fill and drain detected")
        else:
            self.overflow_timer = 0

        # 5. Motor Rotation (E7 series)
        if (phase == 'WASH' or phase.startswith('RINSE')) and rpm < 5:
            self.motor_fail_timer += 1
            if self.motor_fail_timer == 150:
                self._trigger("E7-1", row_index, "Motor failure: No rotation during wash/rinse")
        elif phase == 'SPIN' and rpm < 10:
            self.motor_fail_timer += 1
            if self.motor_fail_timer == 150:
                self._trigger("E7-3", row_index, "Spin failure: Motor stalled during spin cycle")
        else:
            self.motor_fail_timer = 0

        # 6. Unbalance (E3-2)
        if len(history) > 1:
            prev_phase = history[-2].get('phase', 'IDLE')
            if prev_phase == 'SPIN_PAUSE' and phase == 'WATER_FILL':
                self.unbalance_retries += 1
                self.log_callback(f"Unbalance attempt #{self.unbalance_retries}")
                if self.unbalance_retries >= 3:
                    self._trigger("E3-2", row_index, "Critical unbalance: 3 failed recovery attempts")
        if phase == 'IDLE':
            self.unbalance_retries = 0

    def _trigger(self, code, row_index, evidence):
        current_time = row_index
        if code in self._last_log_time and (current_time - self._last_log_time[code]) < 50:
            return
            
        self._last_log_time[code] = current_time
        name = next((e["name"] for e in self.errors_database if e["code"] == code), f"Fault {code}")
        
        self.alarm_triggered.emit(f"Fault {code}: {name} | {evidence}")
        self.log_callback(f"ERROR {code} [{name}]: {evidence}")
        self.record_callback(f"Error {code}", "FAIL", f"Row {row_index}: {evidence}")

    def reset_timers(self):
        self.pump_timer = 0
        self.continuous_pump_timer = 0
        self.pump_cooldown_timer = 0
        self.motor_fail_timer = 0
        self.water_supply_timer = 0
        self.overflow_timer = 0
        self.motor_stuck_timer = 0
        self.leak_timer = 0
        self.unbalance_retries = 0
        self.e2_error_logged = False
        self.ea_error_logged = False
        self.thermal_warning_logged = False
        self._last_log_time = {}
