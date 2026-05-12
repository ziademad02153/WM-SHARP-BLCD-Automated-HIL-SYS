import json
import logging
import os
from PyQt5.QtCore import QObject, pyqtSignal
from error_monitor import ErrorMonitor
from sequence_validator import SequenceValidator

class LogicMonitor(QObject):
    log_event = pyqtSignal(str) # Emits string messages to UI log
    test_result = pyqtSignal(dict) # Emits structured test results for Excel
    phase_changed = pyqtSignal(str) # Emits live phase for UI Dashboard
    validation_status = pyqtSignal(dict) # Forwards SequenceValidator status
    
    def __init__(self):
        super().__init__()
        self.row_index = 0
        self.history = []
        self.analysis_summary = []
        
        # State variables
        self.door_open_timer = 0
        self.weight_test_active = False
        self.weight_sequence_idx = 0
        self.weight_pulse_counter = 0
        self.weight_pulse_start_row = 0
        self.current_phase = 'IDLE'
        self.drain_count = 0
        self._prev_pump = False
        self.leak_timer = 0
        self.unbalance_retries = 0
        
        self.VOLTAGE_THRESHOLD = 2.0  # Lowered to 2.0V since the Softener channel only reaches 2.5V when ON
        self.RPM_SCALE_FACTOR = 1.0  # Hardware (NI MAX / Sensor) already outputs pre-scaled RPM value
        
        # Dynamic program rules
        self.current_program = "Regular"
        self.current_level = 1
        self.m2_cw_sec = 0.5
        self.m2_ccw_sec = 0.5
        
        # Sub-modules
        self.error_monitor = ErrorMonitor(self.log_event.emit, self._record_result_proxy)
        self.sequence_validator = SequenceValidator(self.log_event.emit, self._record_result_proxy)
        self.sequence_validator.validation_status.connect(self.validation_status.emit)
        
    def _record_result_proxy(self, *args, **kwargs):
        self._record_result(*args, **kwargs)

        
    def _load_json_rules(self):
        try:
            if not os.path.exists('wm_config.json'):
                self.log_event.emit("[Info] wm_config.json not found, using sharp_spec.json for all timing rules.")
                return
            with open('wm_config.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            programs = config.get("programs", {})
            # ✅ FIXED: Correct mapping per Sharp VE BLDC Excel Spec Sheet
            # Group 1: Regular, Quick, Baby Care, Quick Rinse
            # Group 2: Jeans, Cotton, Heavy
            # Group 3: Wool, Delicates, Sports Wear
            program_to_group = {
                "Regular":        "Course Group 1",
                "Quick":          "Course Group 1",
                "Baby Care":      "Course Group 1",
                "Quick Rinse":    "Course Group 1",
                "Jeans":          "Course Group 2",
                "Cotton":         "Course Group 2",
                "Heavy":          "Course Group 2",
                "Wool":           "Course Group 3",
                "Delicates":      "Course Group 3",
                "Sports Wear":    "Course Group 3",
                "Blanket":        "Blanket",
                "Tub Clean":      "Tub Clean",
                "Fragrance Rinse Spin": "Fragrance Rinse Spin"
            }
            
            group_key = program_to_group.get(self.current_program, "Course Group 1")
            group_data = programs.get(group_key, {})
            level_str = str(self.current_level)
            
            if level_str in group_data:
                self.m2_cw_sec = group_data[level_str]["m2_cw_sec"]
                self.m2_ccw_sec = group_data[level_str]["m2_ccw_sec"]
                self.log_event.emit(f"[{self.current_program}] Loaded {group_key} Level {self.current_level}: CW={self.m2_cw_sec}s, CCW={self.m2_ccw_sec}s.")
            else:
                fallback = group_data.get("1", {"m2_cw_sec": 0.5, "m2_ccw_sec": 0.5})
                self.m2_cw_sec = fallback["m2_cw_sec"]
                self.m2_ccw_sec = fallback["m2_ccw_sec"]
                self.log_event.emit(f"[{self.current_program}] Level {self.current_level} not found in {group_key}, falling back to Level 1.")
        except Exception as e:
            self.log_event.emit(f"Warning: Could not parse JSON timings, using defaults. ({e})")

    def set_program(self, ui_program_name, level=1):
        # ✅ FIXED: UI to Internal Engine Mapping - matches updated dropdown
        program_map = {
            "Regular (غسيل عادي)":              "Regular",
            "Quick (سريع)":                      "Quick",
            "Heavy (ثقيل/شديد الاتساخ)":        "Heavy",
            "Baby Care (عناية بملابس الأطفال)": "Baby Care",
            "Cotton (قطن)":                      "Cotton",
            "Delicates (ملابس ناعمة/حساسة)":    "Delicates",
            "Wool (صوف)":                        "Wool",
            "Jeans (جينز)":                      "Jeans",
            "Blanket (لحاف)":                    "Blanket",
            "Quick Rinse (شطف سريع)":            "Quick Rinse",
            "Sports Wear (ملابس رياضية)":        "Sports Wear",
            "Tub Clean (تنظيف الحلة)":           "Tub Clean",
        }
        
        self.internal_program_name = program_map.get(ui_program_name, "Regular")
        self.current_program = self.internal_program_name
        self.current_level = level
        self._load_json_rules()
        self.log_event.emit(f"UI Route: [{ui_program_name}] -> Engine parsing: [{self.internal_program_name}] Level {level}")
        
        self.sequence_validator.set_program(self.internal_program_name, f"LEV-{level}")
        
    def process_row(self, data):
        try:
            self.row_index += 1
            
            motor_rpm, cold, hot, softener, gearmotor, empty, pump, door = data[2:]
            
            door_closed = True # TODO: Revert to (door > self.VOLTAGE_THRESHOLD) when wire is connected
            pump_on = pump > self.VOLTAGE_THRESHOLD
            gearmotor_on = gearmotor > self.VOLTAGE_THRESHOLD
            softener_on = softener > self.VOLTAGE_THRESHOLD
            cold_on = cold > self.VOLTAGE_THRESHOLD
            hot_on = hot > self.VOLTAGE_THRESHOLD
            empty_on = empty > self.VOLTAGE_THRESHOLD
            rpm_value = motor_rpm * self.RPM_SCALE_FACTOR  # Convert voltage to RPM

            temp_state = {
                "door_closed": door_closed, 
                "pump_on": pump_on,
                "gearmotor_on": gearmotor_on,
                "softener_on": softener_on,
                "cold_on": cold_on,
                "hot_on": hot_on,
                "empty_on": empty_on,
                "rpm": rpm_value
            }
            
            self._update_phase(temp_state)
            temp_state["phase"] = self.current_phase
            state = temp_state

            self.history.append({"row": self.row_index, **state})
            
            if len(self.history) > 500:
                self.history.pop(0)

            # 1. Logic Sub-Checks
            self._check_child_lock(door_closed, pump_on)
            self._check_weight_detection(rpm_value > 10, rpm_value < 5)
            
            # 2. Main Validation Sub-modules
            self.error_monitor.evaluate_state(self.row_index, state, self.history)
            self.sequence_validator.evaluate_state(self.current_phase)
            
        except Exception as e:
            self.log_event.emit(f"🔴 CRITICAL ENGINE ERROR: {e}")

    def _update_phase(self, state):
        old_phase = self.current_phase
        pump  = state['pump_on']
        cold  = state['cold_on']
        hot   = state['hot_on']
        rpm   = state.get('rpm', 0)
        
        # Track pump state changes to count drain cycles
        prev_pump = getattr(self, '_prev_pump', False)
        
        # Detect falling edge of pump (pump just turned OFF = end of drain)
        if prev_pump and not pump:
            self.drain_count += 1
        self._prev_pump = pump

        # ── STATE MACHINE ────────────────────────────────────────────────
        # IDLE: nothing active
        if self.current_phase == 'IDLE':
            if cold or hot:
                self.drain_count = 0     # reset counter at start of new cycle
                self.current_phase = 'WATER_FILL'
            elif rpm > 10:
                # Motor pulsing without water = Weight Detection
                self.current_phase = 'WEIGHT_DETECT'
            elif rpm > 5 and not (pump or cold or hot):
                # Detected low-speed motor activity at the end (ANTI_WRINKLE)
                self.current_phase = 'ANTI_WRINKLE'

        # WEIGHT_DETECT: motor pulsing to sense load
        elif self.current_phase == 'WEIGHT_DETECT':
            if cold or hot:
                self.current_phase = 'WATER_FILL'
            elif rpm < 5 and not (cold or hot or pump):
                # If it stops for too long without filling, go back to IDLE
                pass

        # WATER_FILL: valve is open, filling with water
        elif self.current_phase == 'WATER_FILL':
            if not cold and not hot:
                # Valves closed - decide what comes next
                if pump:
                    self.current_phase = 'DRAIN'
                else:
                    # After first fill → WASH, after subsequent fills → RINSE N
                    if self.drain_count == 0:
                        self.current_phase = 'WASH'
                    else:
                        self.current_phase = f'RINSE_{self.drain_count}'

        # WASH: motor agitating, no valves, no pump
        elif self.current_phase == 'WASH':
            if pump:
                self.current_phase = 'DRAIN'
            elif cold or hot:
                self.current_phase = 'WATER_FILL'

        # RINSE N: same as wash but post-drain cycle
        elif self.current_phase.startswith('RINSE'):
            if pump:
                self.current_phase = 'DRAIN'
            elif cold or hot:
                self.current_phase = 'WATER_FILL'

        # DRAIN: pump running
        elif self.current_phase == 'DRAIN':
            if not pump:
                if cold or hot:
                    # More water coming → another RINSE fill
                    self.current_phase = 'WATER_FILL'
                else:
                    # End of drain, usually 150s pause before spin
                    self.current_phase = 'SPIN_PAUSE'

        # SPIN_PAUSE: 150s gap for clutch transition
        elif self.current_phase == 'SPIN_PAUSE':
            if rpm > 100:
                self.current_phase = 'SPIN'
            elif cold or hot:
                self.current_phase = 'WATER_FILL'
            elif pump:
                self.current_phase = 'DRAIN'

        # SPIN: motor at high RPM
        elif self.current_phase == 'SPIN':
            if rpm < 30 and not pump and not cold and not hot:
                # After high speed spin, go to IDLE (from where ANTI_WRINKLE might start)
                self.current_phase = 'IDLE'
            elif cold or hot:
                self.current_phase = 'WATER_FILL'

        # ANTI_WRINKLE: pulsator only activity after spin (Rinse part2.png)
        elif self.current_phase == 'ANTI_WRINKLE':
            if rpm < 5 and not (pump or cold or hot):
                self.current_phase = 'IDLE'
            elif pump or cold or hot:
                self.current_phase = 'IDLE' # Transition if new cycle starts

        # ── LOG PHASE CHANGE ─────────────────────────────────────────────
        if old_phase != self.current_phase:
            self.log_event.emit(f"► Phase Shift: [{old_phase}] ➡️  [{self.current_phase}]")
            self.phase_changed.emit(self.current_phase)



        
    def _check_child_lock(self, door_closed, pump_on):
        # ✅ FIXED per Sharp Child Lock Specs:
        # Case A: door closed before 20s → washing continues normally (PASS)
        # Case B: door still open after 20s → pump activates immediately
        if not door_closed:
            self.door_open_timer += 1
            if self.door_open_timer == 200: # 20 seconds at 10Hz
                if not pump_on:
                    msg = f"SAFETY FAIL: Door open >20s - Pump NOT activated (E2 Safety Breach)"
                    self.log_event.emit(msg)
                    self._record_result("Child Lock (E2)", "FAIL", f"Row {self.row_index}: {msg}")
                else:
                    msg = f"✅ SAFETY PASS: Door open >20s - Pump activated correctly (Sharp Spec: Case B)"
                    self.log_event.emit(msg)
                    self._record_result("Child Lock (E2)", "PASS", f"Row {self.row_index}: {msg}")
        else:
            if 0 < self.door_open_timer < 200:
                # Door was opened then closed before 20s - Sharp Spec Case A: continue normally
                elapsed = round(self.door_open_timer / 10, 1)
                msg = f"✅ SAFETY PASS: Door opened then closed after {elapsed}s (<20s) - Machine continues normally (Sharp Spec: Case A)"
                self.log_event.emit(msg)
                self._record_result("Child Lock (E2) Case A", "PASS", f"Row {self.row_index}: {msg}")
            self.door_open_timer = 0
            
    def _check_weight_detection(self, cw_on, ccw_on):
        if self.weight_test_active:
            expected_state = self._get_expected_weight_state(self.weight_sequence_idx)
            is_match = False
            
            if expected_state == 'CCW_ON' and ccw_on and not cw_on:
                is_match = True
            elif expected_state == 'CCW_OFF' and not ccw_on and not cw_on:
                is_match = True
            elif expected_state == 'CW_ON' and cw_on and not ccw_on:
                is_match = True
            elif expected_state == 'CW_OFF' and not cw_on and not ccw_on:
                is_match = True
                
            if is_match:
                self.weight_pulse_counter += 1
                expected_dur = 3 if 'ON' in expected_state else 6
                if self.weight_pulse_counter >= expected_dur:
                    # Log exact duration evidence for the OFF/ON pulses
                    if 'ON' in expected_state:
                         dir_str = "CCW" if "CCW" in expected_state else "CW"
                         dur_ms = self.weight_pulse_counter * 100
                         msg = f"Row {self.weight_pulse_start_row}: Motor {dir_str} Pulse started. Row {self.row_index}: Motor {dir_str} Pulse ended. Total Duration: {dur_ms}ms. Result: PASS."
                         self.log_event.emit(msg)
                         self._record_result(f"Weight Detection ({dir_str} Pulse)", "PASS", msg)
                         
                    self.weight_sequence_idx += 1
                    self.weight_pulse_counter = 0
                    self.weight_pulse_start_row = self.row_index + 1
                    
                    if self.weight_sequence_idx >= 16:
                        msg = f"Row {self.row_index}: Weight Detection full sequence of 4 repeats completed successfully."
                        self.log_event.emit(msg)
                        self._record_result("Weight Detection (Final)", "PASS", msg)
                        self.weight_test_active = False
            else:
                if self.weight_sequence_idx > 0 or self.weight_pulse_counter > 0:
                    dur_ms = self.weight_pulse_counter * 100
                    dir_str = "CCW" if "CCW" in expected_state else "CW"
                    msg = f"Row {self.weight_pulse_start_row}: Motor {dir_str} state started. Row {self.row_index}: Sequence interrupted early at {dur_ms}ms. Result: FAIL."
                    self.log_event.emit(msg)
                    self._record_result("Weight Detection", "FAIL", msg)
                self.weight_test_active = False
                self.weight_sequence_idx = 0
                self.weight_pulse_counter = 0
        else:
            if ccw_on and not cw_on:
                self.weight_test_active = True
                self.weight_sequence_idx = 0
                self.weight_pulse_counter = 1
                self.weight_pulse_start_row = self.row_index
                

    def _get_expected_weight_state(self, idx):
        phase = idx % 4
        return ['CCW_ON', 'CCW_OFF', 'CW_ON', 'CW_OFF'][phase]

    def _record_result(self, test_name, status, evidence, expected=None, actual=None):
        self.analysis_summary.append({
            "Row_Index": self.row_index,
            "Test_Name": test_name,
            "Status": status,
            "Expected_Sec": expected if expected is not None else "N/A",
            "Actual_Sec": actual if actual is not None else "N/A",
            "Technical_Evidence": evidence
        })
        self.test_result.emit(self.analysis_summary[-1])

    def get_summary(self):
        return self.analysis_summary

    def reset(self):
        self.row_index = 0
        self.history.clear()
        # Note: analysis_summary is NOT cleared here if we want to keep results from multiple programs
        # in one Excel export. But usually, one 'Start' = one test. 
        # User wants to switch programs, so we clear it for a clean sheet.
        self.analysis_summary.clear()
        
        self.door_open_timer = 0
        self.weight_test_active = False
        self.weight_sequence_idx = 0
        self.weight_pulse_counter = 0
        self.weight_pulse_start_row = 0
        self.current_phase = 'IDLE'
        self.drain_count = 0
        self._prev_pump = False
        
        # Sub-module resets
        self.error_monitor.reset_timers()
        self.sequence_validator.reset()
