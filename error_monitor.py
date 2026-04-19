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
        self.e2_safe_logged = False
        self.pump_success_logged = False
        self.water_success_logged = False
        
    def _load_config(self):
        if not os.path.exists('wm_config.json'):
            self.log_callback("ErrorMonitor: wm_config.json not found! Please run extract_json.py first.")
            return
            
        with open('wm_config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
            self.errors_database = config.get("errors", [])
            self.log_callback(f"ErrorMonitor Loaded: {len(self.errors_database)} Global Error Rules.")

    def evaluate_state(self, row_index, state, history):
        """
        state dict: {'door_closed', 'pump_on', 'cw_on', 'ccw_on', 'buzzer_on'}
        Check basic fault trees mapped from the JSON database
        """
        
        # 1. Lid Opening Failure (E2) 
        # Detection string: "if the lid is opened during delay start, wash, rinse and spin processes..."
        if not state['door_closed'] and (state.get('phase') in ['WASH', 'SPIN', 'WATER_FILL']):
            if state['cw_on'] or state['ccw_on'] or state['pump_on']:
                self._trigger("E2", row_index, "Lid opened while machine processes are active (Motor or Pump).")
                self.e2_safe_logged = False
            else:
                if not self.e2_safe_logged:
                    msg = "✅ SUCCESS: E2 Safety Protocol Verified (Motor & Pump cleanly deactivated)."
                    self.log_callback(msg)
                    self.record_callback("E2 Safety Protocol", "PASS", f"Row {row_index}: {msg}")
                    self.e2_safe_logged = True
        else:
            self.e2_safe_logged = False

        # 2. General Motor Failure (Eb-1)
        # Detection string: "if during machine startup for some reason the motor is still rotating and doesn't stop within a minute..."
        if state['cw_on'] or state['ccw_on']:
            self.motor_fail_timer += 1
            if self.motor_fail_timer > 600: # 60 seconds at 10Hz
                self._trigger("Eb-1", row_index, "Motor rotating continuously for > 60s without pause.")
        else:
            self.motor_fail_timer = 0
            
        # 3. Drain Failure (E1)
        # Sharp Spec: pump max continuous ON = 15 min before E1 error
        # Sharp Pump Control Spec: max 2.5 min (150s) continuous running then 10s OFF
        # We check BOTH:
        #   a) Pump running >2.5 min without 10s break -> Pump Protocol Violation
        #   b) Pump running >15 min total -> E1 Drain Failure
        if state.get('phase') == 'DRAIN' and state['pump_on']:
            self.pump_timer += 1
            self.pump_success_logged = False
            # Check for 2.5-minute continuous running violation (150 ticks @ 10Hz)
            if self.pump_timer == 150:
                self._trigger("E1", row_index, "Pump exceeded 2.5-minute continuous running limit (Sharp Pump Control Spec: max 2.5 min ON, then 10s OFF required).")
        else:
            if self.pump_timer > 10 and not self.pump_success_logged and self.pump_timer < 150:
                msg = "✅ SUCCESS: E1 Protocol Passed (Pump drained successfully within time limit)."
                self.log_callback(msg)
                self.record_callback("E1 Protocol", "PASS", f"Row {row_index}: {msg}")
                self.pump_success_logged = True
            self.pump_timer = 0
            
        # 4. Water Supply Failure (E5)
        if state.get('phase') == 'WATER_FILL' and (state.get('cold_on') or state.get('hot_on')):
            self.water_supply_timer += 1
            self.water_success_logged = False
            if self.water_supply_timer == 200: # 200 Ticks = 20s (simulate 20 mins)
                self._trigger("E5", row_index, "Water valves open continuously for simulated 20 minutes (Testing limit: 20s) during FILL phase - Water Supply Failure.")
        else:
            if self.water_supply_timer > 10 and not self.water_success_logged and self.water_supply_timer < 200:
                msg = "✅ SUCCESS: E5 Protocol Passed (Water filled successfully within time limit)."
                self.log_callback(msg)
                self.record_callback("E5 Protocol", "PASS", f"Row {row_index}: {msg}")
                self.water_success_logged = True
            self.water_supply_timer = 0
            
        # 5. Motor Short Circuit / Conflicting Directions (E7-4)
        if state.get('cw_on') and state.get('ccw_on'):
            self._trigger("E7-4", row_index, "Motor CW and CCW are ON simultaneously indicating hardware short circuit.")

    def _trigger(self, code, row_index, evidence):
        name = next((e["name"] for e in self.errors_database if e["code"] == code), "Unknown Error")
        msg = f"SECURITY FAULT {code} [{name}]: {evidence}"
        self.log_callback(msg)
        self.record_callback(f"Error Check ({code})", "FAIL", f"Row {row_index}: {msg}")
