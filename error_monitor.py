import json
import os

class ErrorMonitor:
    def __init__(self, log_callback, record_callback):
        self.log_callback = log_callback
        self.record_callback = record_callback
        
        self.errors_database = []
        self._load_config()

        # State trackers for error detection
        self.pump_timer = 0
        self.motor_fail_timer = 0
        self.water_supply_timer = 0
        self.overflow_timer = 0
        self.motor_stuck_timer = 0
        
        # Success logging flags
        self.e2_safe_logged = False
        self.e2_error_logged = False
        self.ea_error_logged = False
        self.pump_success_logged = False
        self.water_success_logged = False
        
    def _load_config(self):
        # Prefer sharp_spec.json as the master knowledge base
        spec_path = 'sharp_spec.json'
        if not os.path.exists(spec_path):
            self.log_callback(f"ErrorMonitor: {spec_path} not found! Falling back to wm_config.json")
            spec_path = 'wm_config.json'
            
        try:
            with open(spec_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                self.errors_database = config.get("errors", [])
                self.log_callback(f"ErrorMonitor: Loaded {len(self.errors_database)} error rules from {spec_path}")
        except Exception as e:
            self.log_callback(f"ErrorMonitor Load Error: {e}")

    def evaluate_state(self, row_index, state, history):
        """
        Ultra-Premium A-to-Z Error Detection based on Sharp Factory Specs
        """
        phase = state.get('phase', 'IDLE')
        rpm = state.get('rpm', 0)
        pump = state.get('pump_on', False)
        empty = state.get('empty_on', False) 
        cold = state.get('cold_on', False)
        hot = state.get('hot_on', False)
        door_closed = state.get('door_closed', True)
        
        # 1. Lid Opening Failure (E2) 
        # Sharp Spec: Lid opened during process (WASH, RINSE, SPIN, FILL, DELAY START).
        if not door_closed and (phase in ['WASH', 'SPIN', 'WATER_FILL', 'WEIGHT_DETECT'] or phase.startswith('RINSE')):
            if pump or rpm > 15 or cold or hot:
                if not self.e2_error_logged:
                    self._trigger("E2", row_index, f"SAFETY FAULT: Lid opened while machine active! Phase: {phase}")
                    self.e2_error_logged = True
            else:
                if not self.e2_safe_logged:
                    self.log_callback(f"✅ SAFETY PASS: Machine stopped correctly on lid open during {phase}.")
                    self.record_callback("E2 Door Safety", "PASS", f"Row {row_index}: Valid stop detected.")
                    self.e2_safe_logged = True
        else:
            self.e2_safe_logged = False
            self.e2_error_logged = False

        # 2. Drain Failure (E1) - 15 min limit
        if (phase == 'DRAIN' or pump) and not empty:
            self.pump_timer += 1
            if self.pump_timer == 9000: # 15 min
                self._trigger("E1", row_index, "Drain Failure: Reset level not reached in 15 mins.")
        else:
            self.pump_timer = 0
            
        # 3. Water Supply Failure (E5) - 20 min limit
        if phase == 'WATER_FILL' and (cold or hot):
            self.water_supply_timer += 1
            if self.water_supply_timer == 12000: # 20 min
                self._trigger("E5", row_index, "Water Supply Failure: Fill exceeded 20 mins.")
        else:
            self.water_supply_timer = 0
            
        # 4. Overflow Failure (E6-1) - 5 min concurrent fill/pump
        if (cold or hot) and pump:
            self.overflow_timer += 1
            if self.overflow_timer == 3000: 
                self._trigger("E6-1", row_index, "Overflow Failure: Inlet & Pump active for > 5 mins.")
        else:
            self.overflow_timer = 0

        # 5. Motor Rotation Failures (E7 series)
        # E7-1/2/4: Motor doesn't rotate during WASH
        if (phase == 'WASH' or phase.startswith('RINSE')) and rpm < 5:
            self.motor_fail_timer += 1
            if self.motor_fail_timer == 150: # 15 seconds of agitation phase without RPM
                self._trigger("E7-1", row_index, "Motor Rotation Failure: No movement detected during agitation.")
        # E7-3: Motor doesn't rotate during SPIN
        elif phase == 'SPIN' and rpm < 10:
            self.motor_fail_timer += 1
            if self.motor_fail_timer == 150:
                self._trigger("E7-3", row_index, "Spin Rotation Failure: Motor not reaching speed during SPIN phase.")
        else:
            self.motor_fail_timer = 0

        # 6. Abnormal Water Leakage (E9)
        # Sharp Spec: If during wash (not filling) there is no water (Empty = True)
        if (phase == 'WASH' or phase.startswith('RINSE')) and empty:
            self.leak_timer = getattr(self, 'leak_timer', 0) + 1
            if self.leak_timer == 300: # 30 seconds of empty tub during wash
                self._trigger("E9", row_index, "Abnormal Water Leakage: Tub empty during active wash cycle.")
        else:
            self.leak_timer = 0

        # 7. Abnormal Water When Dry (EA)
        if phase == 'SPIN' and not empty and rpm > 100:
            if not getattr(self, 'ea_error_logged', False):
                self._trigger("EA", row_index, "Abnormal Water: Water in tub during high-speed spin.")
                self.ea_error_logged = True
        else:
            self.ea_error_logged = False

        # 8. General Motor Failure (Eb-1)
        # If at IDLE/Startup motor rotates > 1 min
        if phase == 'IDLE' and rpm > 10:
            self.motor_stuck_timer += 1
            if self.motor_stuck_timer == 600:
                self._trigger("Eb-1", row_index, "General Motor Failure: Spontaneous rotation during IDLE.")
        else:
            self.motor_stuck_timer = 0

        # 9. Unbalance Failure (E3-2)
        prev_phase = history[-2].get('phase', 'IDLE') if len(history) > 1 else 'IDLE'
        if prev_phase == 'SPIN_PAUSE' and phase == 'WATER_FILL':
            self.unbalance_retries = getattr(self, 'unbalance_retries', 0) + 1
            self.log_callback(f"⚠️ UNBALANCE ATTEMPT #{self.unbalance_retries}")
            if self.unbalance_retries >= 3:
                self._trigger("E3-2", row_index, "Unbalance Failure: 3 failed correction attempts.")
        if phase == 'IDLE': self.unbalance_retries = 0

    def _trigger(self, code, row_index, evidence):
        name = next((e["name"] for e in self.errors_database if e["code"] == code), f"Fault {code}")
        msg = f"🔴 ERROR {code} [{name}]: {evidence}"
        self.log_callback(msg)
        self.record_callback(f"Error Code: {code}", "FAIL", f"Row {row_index}: {evidence}")

    def reset_timers(self):
        self.pump_timer = 0
        self.motor_fail_timer = 0
        self.water_supply_timer = 0
        self.overflow_timer = 0
        self.motor_stuck_timer = 0
        self.leak_timer = 0
        self.unbalance_retries = 0
        self.e2_error_logged = False
        self.ea_error_logged = False
        # Optional: any other dynamic flags
        if hasattr(self, 'motor_fail_timer'): self.motor_fail_timer = 0
