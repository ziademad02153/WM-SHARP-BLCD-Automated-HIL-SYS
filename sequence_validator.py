import json
import os
from PyQt5.QtCore import QObject, pyqtSignal

class SequenceValidator(QObject):
    validation_status = pyqtSignal(dict) # To update UI (expected phase, time left, pass/fail)

    def __init__(self, log_callback, record_callback):
        super().__init__()
        self.log_callback = log_callback
        self.record_callback = record_callback
        
        self.spec = {}
        self.sequence_chart = {}
        self.course_options = {}
        self._load_config()

        self.current_program = None
        self.current_level = None
        
        # Validation State
        self.expected_phases = []
        self.current_step_index = 0
        self.time_in_current_phase = 0
        self.last_phase = 'IDLE'
        self.is_failed = False
        
        self.TOLERANCE_SEC = 15 # 15 seconds tolerance

    def _load_config(self):
        try:
            with open('sharp_spec.json', 'r', encoding='utf-8') as f:
                self.spec = json.load(f)
                self.sequence_chart = self.spec.get("sequence_chart", {})
                self.course_options = self.spec.get("course_option_detail", {})
                self.log_callback(f"SequenceValidator: Loaded Sharp specification logic.")
        except Exception as e:
            self.log_callback(f"SequenceValidator Load Error: {e}")

    def set_program(self, program_name, level):
        """Builds a linear list of expected phases based on Sharp specifications"""
        self.current_program = program_name
        self.current_level = level
        self.expected_phases = []
        self.current_step_index = 0
        self.time_in_current_phase = 0
        self.last_phase = 'IDLE'
        self.is_failed = False
        
        if program_name not in self.sequence_chart or level not in self.sequence_chart[program_name]:
            self.log_callback(f"SequenceValidator: Program '{program_name}' Level '{level}' not found in spec!")
            return

        times = self.sequence_chart[program_name][level]
        options = self.course_options.get(program_name, {})
        
        # 1. Weight Detection
        if options.get("weight_detection", False):
            self.expected_phases.append({"name": "WEIGHT_DETECT", "duration_sec": 7, "type": "strict"})

        # 2. Main Wash
        main_wash_sec = times.get("main_wash_sec", 0)
        if main_wash_sec > 0:
            self.expected_phases.append({"name": "WATER_FILL", "duration_sec": times.get("water_fill_sec", 180), "type": "max_limit"})
            self.expected_phases.append({"name": "WASH", "duration_sec": main_wash_sec, "type": "strict"})

        # 3. Rinses
        rinse_count = times.get("rinse_count", 0)
        for i in range(rinse_count):
            self.expected_phases.append({"name": "DRAIN", "duration_sec": times.get("drain_sec", 120), "type": "max_limit"})
            self.expected_phases.append({"name": "SPIN", "duration_sec": times.get("balance_spin_sec", 180), "type": "strict"})
            self.expected_phases.append({"name": "WATER_FILL", "duration_sec": times.get("water_fill_sec", 180), "type": "max_limit"})
            self.expected_phases.append({"name": "WASH", "duration_sec": times.get("rinse_wash_sec", 120), "type": "strict"}) # RINSE maps to WASH electrically

        # 4. Final Spin
        if times.get("final_spin_sec", 0) > 0:
            self.expected_phases.append({"name": "DRAIN", "duration_sec": times.get("drain_sec", 120), "type": "max_limit"})
            self.expected_phases.append({"name": "SPIN", "duration_sec": times.get("final_spin_sec", 300), "type": "strict"})

        self.log_callback(f"SequenceValidator: Built sequence map for {program_name} {level}. Total steps: {len(self.expected_phases)}")
        self._emit_status()

    def evaluate_state(self, actual_phase):
        if self.is_failed or not self.expected_phases or self.current_step_index >= len(self.expected_phases):
            return

        expected_step = self.expected_phases[self.current_step_index]
        expected_phase_name = expected_step["name"]
        
        # Tracking Time
        if actual_phase != 'IDLE':
            self.time_in_current_phase += 1  # 1 tick = 100ms
            
        time_sec = self.time_in_current_phase / 10.0

        # Phase Transition Logic
        if actual_phase != self.last_phase and self.last_phase != 'IDLE':
            # Machine changed phase! Let's check if it was supposed to
            if self.last_phase == expected_phase_name:
                # Did it spend the right amount of time?
                target_time = expected_step["duration_sec"]
                
                if expected_step["type"] == "strict":
                    if abs(time_sec - target_time) > self.TOLERANCE_SEC:
                        self._trigger_fail(f"Phase '{expected_phase_name}' took {time_sec:.1f}s, expected {target_time}s (±{self.TOLERANCE_SEC}s tolerance).")
                        return
                elif expected_step["type"] == "max_limit":
                    if time_sec > target_time + self.TOLERANCE_SEC:
                        self._trigger_fail(f"Phase '{expected_phase_name}' took {time_sec:.1f}s, exceeded max limit of {target_time}s.")
                        return

                # It passed the time check! Move to next expected phase
                self._record_pass(expected_phase_name, target_time, time_sec)
                self.current_step_index += 1
                self.time_in_current_phase = 0
                
                if self.current_step_index < len(self.expected_phases):
                    next_expected = self.expected_phases[self.current_step_index]["name"]
                    if actual_phase != next_expected and actual_phase != 'IDLE':
                        self._trigger_fail(f"Wrong Transition: Expected '{next_expected}', but machine went to '{actual_phase}'.")
                        return

        # Time over-run check without transition
        if actual_phase == expected_phase_name:
            target_time = expected_step["duration_sec"]
            if time_sec > target_time + self.TOLERANCE_SEC:
                 self._trigger_fail(f"Phase '{expected_phase_name}' has been running for {time_sec:.1f}s, exceeding target of {target_time}s.")
                 return

        self.last_phase = actual_phase
        self._emit_status()

    def _trigger_fail(self, reason):
        self.is_failed = True
        msg = f"❌ SEQUENCE FAIL: {reason}"
        self.log_callback(msg)
        self.record_callback("Sequence Validation", "FAIL", msg)
        self._emit_status()

    def _record_pass(self, phase, expected_time, actual_time):
        msg = f"✅ SEQUENCE PASS: {phase} completed in {actual_time:.1f}s (Expected: {expected_time}s)"
        self.log_callback(msg)
        self.record_callback(f"Phase Validator: {phase}", "PASS", msg)

    def _emit_status(self):
        if not self.expected_phases or self.current_step_index >= len(self.expected_phases):
            status = {"expected_phase": "Finished/Idle", "time_left": 0, "status": "FAIL" if self.is_failed else "IDLE"}
        else:
            expected_step = self.expected_phases[self.current_step_index]
            time_left = max(0, expected_step["duration_sec"] - (self.time_in_current_phase / 10.0))
            status = {
                "expected_phase": expected_step["name"],
                "time_left": time_left,
                "status": "FAIL" if self.is_failed else "RUNNING"
            }
        self.validation_status.emit(status)
