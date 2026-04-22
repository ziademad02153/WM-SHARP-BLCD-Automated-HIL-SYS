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
        state dict: {
            'door_closed', 'pump_on', 'cw_on', 'ccw_on', 
            'cold_on', 'hot_on', 'clutch_on', 'buzzer_on',
            'phase', 'motor_rpm', 'motor_voltage'
        }
        """
        
        # 1. Lid Opening Failure (E2) 
        # Sharp: Lid opened during process (WASH/RINSE/SPIN)
        if not state['door_closed'] and (state.get('phase') in ['WASH', 'RINSE', 'SPIN']):
            # If motor or pump still running while door open -> Fault
            if state['cw_on'] or state['ccw_on'] or state['pump_on'] or state.get('motor_rpm', 0) > 10:
                self._trigger("E2", row_index, f"Lid opened while machine active! Phase: {state.get('phase')}. Motor RPM: {state.get('motor_rpm')}")
                self.e2_safe_logged = False
            else:
                if not self.e2_safe_logged:
                    self.log_callback("✅ SUCCESS: E2 Safety Protocol Verified (Stopped correctly on lid open).")
                    self.record_callback("E2 Safety", "PASS", f"Row {row_index}: Machine stopped on door open.")
                    self.e2_safe_logged = True
        else:
            self.e2_safe_logged = False

        # 2. General Motor / Stuck Rotation (Eb-1)
        # Sharp: Motor rotates continuously > 1 min at startup or when it should be idle
        if (state.get('phase') in ['IDLE', 'PAUSE']) and (state['cw_on'] or state['ccw_on'] or state.get('motor_rpm', 0) > 5):
            self.motor_stuck_timer += 1
            if self.motor_stuck_timer > 600: # 60s at 10Hz
                self._trigger("Eb-1", row_index, "Motor rotating during IDLE/PAUSE for > 60 seconds.")
        else:
            self.motor_stuck_timer = 0
            
        # 3. Drain Failure (E1)
        # Sharp: 15 min total limit, or 2.5 min continuous running violation
        if state.get('phase') == 'DRAIN' and state['pump_on']:
            self.pump_timer += 1
            self.pump_success_logged = False
            # Check for 2.5-minute continuous running violation (150s = 1500 ticks @ 10Hz?)
            # Adjusting to 150 ticks = 15s for faster testing demonstration, should be 1500 for real
            if self.pump_timer == 1500: 
                self._trigger("E1", row_index, "Pump exceeded 150s continuous run (Sharp Spec: 2.5 min ON, 10s OFF required).")
        else:
            self.pump_timer = 0
            
        # 4. Water Supply Failure (E5)
        # Sharp: 20 min limit
        if state.get('phase') == 'WATER_FILL' and (state.get('cold_on') or state.get('hot_on')):
            self.water_supply_timer += 1
            if self.water_supply_timer == 12000: # 20 mins = 1200s = 12000 ticks @ 10Hz
                self._trigger("E5", row_index, "Water supply timed out (> 20 minutes) during FILL phase.")
        else:
            self.water_supply_timer = 0
            
        # 5. Overflow Failure (E6-1)
        # Sharp: Inlet ON + Pump ON during overflow condition
        if (state.get('cold_on') or state.get('hot_on')) and state['pump_on']:
            self.overflow_timer += 1
            if self.overflow_timer > 100: # 10 seconds of overlap
                self._trigger("E6-1", row_index, "Overflow Detected: Inlets AND Pump active simultaneously for > 10s.")
        else:
            self.overflow_timer = 0

        # 6. Abnormal Water when Dry (EA)
        # Sharp: Water in tub (Pump activates) during SPIN phase
        if state.get('phase') == 'SPIN' and state['pump_on']:
            # Pump should only run at start of spin, not during the high RPM phase
            if state.get('motor_rpm', 0) > 200:
                self._trigger("EA", row_index, "Abnormal water detected during High-Speed Spin (Pump activated).")

        # 7. Motor Phase / Direction Failures (E7 series)
        if state.get('phase') == 'WASH':
            # Motor Short (E7-4)
            if state.get('cw_on') and state.get('ccw_on'):
                self._trigger("E7-4", row_index, "Motor CW and CCW ON simultaneously (Hardware Short Circuit).")
            
            # Rotation Failures (Requires expected direction from sequence)
            # If sequence says CW and RPM = 0 -> E7-1
            # If sequence says CCW and RPM = 0 -> E7-2

    def _trigger(self, code, row_index, evidence):
        name = next((e["name"] for e in self.errors_database if e["code"] == code), "Unknown Error")
        msg = f"SECURITY FAULT {code} [{name}]: {evidence}"
        self.log_callback(msg)
        self.record_callback(f"Error Check ({code})", "FAIL", f"Row {row_index}: {msg}")

    def reset_timers(self):
        self.pump_timer = 0
        self.motor_fail_timer = 0
        self.water_supply_timer = 0
        self.overflow_timer = 0
        self.motor_stuck_timer = 0
