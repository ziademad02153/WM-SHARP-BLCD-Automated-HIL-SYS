import json
import logging
import os
from PyQt5.QtCore import QObject, pyqtSignal
from error_monitor import ErrorMonitor
from sequence_validator import SequenceValidator

class LogicMonitor(QObject):
    log_event = pyqtSignal(str) 
    test_result = pyqtSignal(dict) 
    phase_changed = pyqtSignal(str) 
    validation_status = pyqtSignal(dict) 
    
    def __init__(self):
        super().__init__()
        self.row_index = 0
        self.history = []
        self.analysis_summary = []
        
        self.door_open_timer = 0
        self.weight_test_active = False
        self.weight_sequence_idx = 0
        self.weight_pulse_counter = 0
        self.current_phase = 'IDLE'
        self.drain_count = 0
        self._prev_pump = False
        self.has_filled = False
        
        self.VOLTAGE_THRESHOLD = 2.0  
        self.RPM_SCALE_FACTOR = 1.0  
        
        self.current_program = "Regular"
        self.current_level = 1
        
        self.error_monitor = ErrorMonitor(self.log_event.emit, self._record_result_proxy)
        self.sequence_validator = SequenceValidator(self.log_event.emit, self._record_result_proxy)
        self.sequence_validator.validation_status.connect(self.validation_status.emit)
        
    def _record_result_proxy(self, *args, **kwargs):
        self._record_result(*args, **kwargs)

    def set_program(self, ui_program_name, level=1):
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
        self.log_event.emit(f"UI Route: [{ui_program_name}] -> Engine parsing: [{self.internal_program_name}] Level {level}")
        self.sequence_validator.set_program(self.internal_program_name, f"LEV-{level}")
        
    def process_row(self, data):
        try:
            self.row_index += 1
            motor_rpm, cold, hot, softener, gearmotor, empty, pump, door = data[2:]
            
            door_closed = True 
            pump_on = pump > self.VOLTAGE_THRESHOLD
            gearmotor_on = gearmotor > self.VOLTAGE_THRESHOLD
            softener_on = softener > self.VOLTAGE_THRESHOLD
            cold_on = cold > self.VOLTAGE_THRESHOLD
            hot_on = hot > self.VOLTAGE_THRESHOLD
            empty_on = empty > self.VOLTAGE_THRESHOLD
            rpm_value = motor_rpm * self.RPM_SCALE_FACTOR

            state = {
                "door_closed": door_closed, 
                "pump_on": pump_on,
                "gearmotor_on": gearmotor_on,
                "softener_on": softener_on,
                "cold_on": cold_on,
                "hot_on": hot_on,
                "empty_on": empty_on,
                "rpm": rpm_value
            }
            
            self._update_phase(state)
            state["phase"] = self.current_phase
            self.history.append({"row": self.row_index, **state})
            if len(self.history) > 500: self.history.pop(0)

            self._check_child_lock(door_closed, pump_on)
            self._check_weight_detection(rpm_value > 30, rpm_value < 5)
            self.error_monitor.evaluate_state(self.row_index, state, self.history)
            self.sequence_validator.evaluate_state(self.current_phase)
        except Exception as e:
            self.log_event.emit(f"🔴 CRITICAL ENGINE ERROR: {e}")

    def _update_phase(self, state):
        old_phase = self.current_phase
        pump  = state['pump_on']
        gear  = state['gearmotor_on']
        cold  = state['cold_on']
        hot   = state['hot_on']
        rpm   = state['rpm']
        
        prev_pump = getattr(self, '_prev_pump', False)
        if prev_pump and not pump: self.drain_count += 1
        self._prev_pump = pump

        if pump or gear:
            if rpm > 40: self.current_phase = 'SPIN'
            else: self.current_phase = 'DRAIN'
        elif cold or hot:
            self.current_phase = 'WATER_FILL'
            self.has_filled = True
        elif rpm > 30:
            if not self.has_filled: self.current_phase = 'WEIGHT_DETECT'
            else: self.current_phase = 'WASH'
        elif rpm > 5:
            if not self.has_filled: self.current_phase = 'WEIGHT_DETECT'
            else: self.current_phase = 'WASH'
        else:
            if not self.has_filled and old_phase == 'WEIGHT_DETECT':
                pass # Stay in WD during gaps
            else:
                self.current_phase = 'IDLE'

        if old_phase != self.current_phase:
            self.log_event.emit(f"► Phase Shift: [{old_phase}] ➡️  [{self.current_phase}]")
            self.phase_changed.emit(self.current_phase)
        
    def _check_child_lock(self, door_closed, pump_on):
        if not door_closed:
            self.door_open_timer += 1
            if self.door_open_timer == 200: 
                if not pump_on: self._record_result("Child Lock (E2)", "FAIL", "Door open >20s - Pump NOT activated")
                else: self._record_result("Child Lock (E2)", "PASS", "Door open >20s - Pump activated correctly")
        else: self.door_open_timer = 0
            
    def _check_weight_detection(self, active, idle):
        if self.weight_test_active:
            expected = self._get_expected_weight_state(self.weight_sequence_idx)
            is_match = (('ON' in expected and active) or ('OFF' in expected and idle))
            if is_match:
                self.weight_pulse_counter += 1
                if self.weight_pulse_counter >= (3 if 'ON' in expected else 6):
                    self.weight_sequence_idx += 1
                    self.weight_pulse_counter = 0
                    if self.weight_sequence_idx >= 16:
                        self.log_event.emit("✅ WEIGHT DETECTION PASS")
                        self._record_result("Weight Detection", "PASS", "Full sequence completed")
                        self.weight_test_active = False
            else:
                if self.weight_sequence_idx > 4:
                    self._record_result("Weight Detection", "FAIL", f"Interrupted at step {self.weight_sequence_idx}")
                self.weight_test_active = False
                self.weight_sequence_idx = 0
                self.weight_pulse_counter = 0
        else:
            if active and self.current_phase == 'WEIGHT_DETECT':
                self.weight_test_active = True
                self.weight_sequence_idx = 0
                self.weight_pulse_counter = 1

    def _get_expected_weight_state(self, idx):
        return ['CCW_ON', 'CCW_OFF', 'CW_ON', 'CW_OFF'][idx % 4]

    def _record_result(self, test_name, status, evidence):
        self.analysis_summary.append({"Row": self.row_index, "Test": test_name, "Status": status, "Evidence": evidence})
        self.test_result.emit(self.analysis_summary[-1])

    def reset(self):
        self.row_index = 0
        self.history.clear()
        self.analysis_summary.clear()
        self.door_open_timer = 0
        self.weight_test_active = False
        self.weight_sequence_idx = 0
        self.weight_pulse_counter = 0
        self.current_phase = 'IDLE'
        self.drain_count = 0
        self.has_filled = False
        self._prev_pump = False
        self.sequence_validator.reset()
