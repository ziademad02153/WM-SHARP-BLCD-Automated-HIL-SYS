import json
import logging
from PyQt5.QtCore import QObject, pyqtSignal
from error_monitor import ErrorMonitor

class LogicMonitor(QObject):
    log_event = pyqtSignal(str) # Emits string messages to UI log
    test_result = pyqtSignal(dict) # Emits structured test results for Excel
    phase_changed = pyqtSignal(str) # Emits live phase for UI Dashboard
    
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
        
        self.VOLTAGE_THRESHOLD = 3.0
        
        # Dynamic program rules
        self.current_program = "Regular"
        self.current_level = 1
        self.m2_cw_sec = 0.5
        self.m2_ccw_sec = 0.5
        
        # Sub-modules
        self.error_monitor = ErrorMonitor(self.log_event.emit, self._record_result_proxy)
        
    def _record_result_proxy(self, name, status, evidence):
        self._record_result(name, status, evidence)

        
    def _load_json_rules(self):
        try:
            with open('wm_config.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            programs = config.get("programs", {})
            program_to_group = {
                "Cotton": "Course Group 1",
                "Regular": "Course Group 1",
                "Delicates": "Course Group 3",
                "Wool": "Course Group 3",
                "Heavy": "Course Group 2",
                "Jeans": "Course Group 2",
                "Sports Wear": "Course Group 3",
                "Baby Care": "Course Group 2",
                "Quick": "Quick",
                "Blanket": "Blanket",
                "Tub Clean": "Tub Clean",
                "Rinse": "Fragrance Rinse Spin",
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
        # UI to Excel Sheet Mapping Layer
        program_map = {
            "Cotton (قطن)": "Cotton",
            "Eco (توفير - البرنامج الاقتصادي)": "Regular",
            "Mix (مختلط)": "Regular",
            "Quick Wash (غسيل سريع)": "Quick",
            "Wool (صوف)": "Wool",
            "Delicate (ملابس ناعمة/حساسة)": "Delicates",
            "Heavy Duty (ثقيل/شديد الاتساخ)": "Heavy",
            "Blanket (لحاف)": "Blanket",
            "Baby Care (عناية بملابس الأطفال)": "Baby Care",
            "Sportswear (ملابس رياضية)": "Sports Wear",
            "Jeans (جينز)": "Jeans",
            "Drum Clean (تنظيف الحلة)": "Tub Clean",
            "Rinse + Spin (شطف وعصر)": "Rinse",
            "Spin Only (عصر فقط)": "Fragrance Rinse Spin",
            "Drain (تصريف المياه فقط)": "Fragrance Rinse Spin"
        }
        
        self.internal_program_name = program_map.get(ui_program_name, "Regular")
        self.current_program = self.internal_program_name
        self.current_level = level
        self._load_json_rules()
        self.log_event.emit(f"UI Route: [{ui_program_name}] -> Engine parsing: [{self.internal_program_name}] Level {level}")
        
    def process_row(self, data):
        self.row_index += 1
        
        cold, hot, pump, clutch, cw, ccw, door, buzzer = data[2:]
        
        door_closed = door > self.VOLTAGE_THRESHOLD
        pump_on = pump > self.VOLTAGE_THRESHOLD
        cw_on = cw > self.VOLTAGE_THRESHOLD
        ccw_on = ccw > self.VOLTAGE_THRESHOLD
        buzzer_on = buzzer > self.VOLTAGE_THRESHOLD
        cold_on = cold > self.VOLTAGE_THRESHOLD
        hot_on = hot > self.VOLTAGE_THRESHOLD

        temp_state = {
            "door_closed": door_closed, 
            "pump_on": pump_on,
            "cw_on": cw_on, 
            "ccw_on": ccw_on, 
            "buzzer_on": buzzer_on,
            "cold_on": cold_on,
            "hot_on": hot_on
        }
        
        self._update_phase(temp_state)
        temp_state["phase"] = self.current_phase
        state = temp_state

        self.history.append({"row": self.row_index, **state})
        
        if len(self.history) > 500:
            self.history.pop(0)

        # 1. Native Checks
        self._check_child_lock(door_closed, pump_on)
        self._check_weight_detection(cw_on, ccw_on)
        
        # 2. Global Error Fault Tree evaluate
        self.error_monitor.evaluate_state(self.row_index, state, self.history)

    def _update_phase(self, state):
        old_phase = self.current_phase
        
        if self.current_phase == 'IDLE':
            if state['cw_on'] or state['ccw_on']:
                self.current_phase = 'WEIGHT_DETECT'
            elif state['cold_on'] or state['hot_on']:
                self.current_phase = 'WATER_FILL'
                
        elif self.current_phase == 'WEIGHT_DETECT':
            if state['cold_on'] or state['hot_on']:
                self.current_phase = 'WATER_FILL'
                
        elif self.current_phase == 'WATER_FILL':
            if not state['cold_on'] and not state['hot_on']:
                if state['cw_on'] or state['ccw_on']:
                    self.current_phase = 'WASH'
                elif state['pump_on']:
                    self.current_phase = 'DRAIN'
                    
        elif self.current_phase == 'WASH':
            if state['pump_on']:
                self.current_phase = 'DRAIN'
            elif state['cold_on'] or state['hot_on']:
                self.current_phase = 'WATER_FILL'
                
        elif self.current_phase == 'DRAIN':
            if not state['pump_on']:
                if state['cw_on'] or state['ccw_on']:
                    self.current_phase = 'SPIN'
                elif state['cold_on'] or state['hot_on']:
                    self.current_phase = 'WATER_FILL'
                    
        elif self.current_phase == 'SPIN':
            if not state['cw_on'] and not state['ccw_on'] and not state['pump_on']:
                 self.current_phase = 'IDLE'

        if old_phase != self.current_phase:
            self.log_event.emit(f"► System Phase Shift: [{old_phase}] ➡️  [{self.current_phase}]")
            self.phase_changed.emit(self.current_phase)

        
    def _check_child_lock(self, door_closed, pump_on):
        if not door_closed:
            self.door_open_timer += 1
            if self.door_open_timer == 200: # 20 seconds at 10Hz
                if not pump_on:
                    msg = f"SAFETY FAIL: Door open for 20s without Pump activation"
                    self.log_event.emit(msg)
                    self._record_result("Child Lock", "FAIL", f"Row {self.row_index}: {msg}")
                else:
                    msg = f"SAFETY PASS: Door open for 20s, Pump activated successfully."
                    self.log_event.emit(msg)
                    self._record_result("Child Lock", "PASS", f"Row {self.row_index}: {msg}")
        else:
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

    def _record_result(self, test_name, status, evidence):
        self.analysis_summary.append({
            "Row_Index": self.row_index,
            "Test_Name": test_name,
            "Status": status,
            "Technical_Evidence": evidence
        })
        self.test_result.emit(self.analysis_summary[-1])

    def get_summary(self):
        return self.analysis_summary

    def reset(self):
        self.row_index = 0
        self.history.clear()
        self.analysis_summary.clear()
        self.door_open_timer = 0
        self.weight_test_active = False
        self.weight_sequence_idx = 0
        self.weight_pulse_counter = 0
        self.weight_pulse_start_row = 0
        self.current_phase = 'IDLE'
