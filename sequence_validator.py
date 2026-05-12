import json
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
        
        # Normalize program name for mapping
        prog_key = program_name.replace(" ", "_")
        
        if program_name not in self.sequence_chart or level not in self.sequence_chart[program_name]:
            self.log_callback(f"SequenceValidator: Program '{program_name}' Level '{level}' not found in spec!")
            return

        times = self.sequence_chart[program_name][level]
        # Check course options for special flags (like weight detection)
        options = self.course_options.get(prog_key, {})
        if not options:
             # Fallback to display name if underscore mapping fails
             options = self.course_options.get(program_name, {})

        # 1. Weight Detection (Standard on most programs)
        # Default is True unless specified False in spec
        wd_enabled = options.get("weight_detection", True)
        if wd_enabled:
            self.expected_phases.append({"name": "WEIGHT_DETECT", "duration_sec": 7.2, "type": "strict"})

        # 2. Main Wash (Note: Quick Rinse skips this)
        main_wash_sec = times.get("main_wash_sec", 0)
        if main_wash_sec is not None and main_wash_sec > 0:
            self.expected_phases.append({"name": "WATER_FILL", "duration_sec": times.get("water_fill_sec", 180), "type": "max_limit"})
            self.expected_phases.append({"name": "WASH", "duration_sec": main_wash_sec, "type": "strict"})

        # 3. Rinses
        rinse_count = times.get("rinse_count", 0)
        if rinse_count is not None:
            for i in range(1, rinse_count + 1):
                # Every rinse starts with a DRAIN from previous phase
                self.expected_phases.append({"name": "DRAIN", "duration_sec": times.get("drain_sec", 120), "type": "max_limit"})
                
                # 150s Pause after drain before spin (Clutch shift)
                self.expected_phases.append({"name": "SPIN_PAUSE", "duration_sec": 150, "type": "strict"})
                
                # Intermediate spins: Balance (180s) + Medium Spin
                # Quick mode has 40s Medium Spin = 220s total. Others 120s = 300s total.
                spin_dur = 220 if "Quick" in program_name else 300
                self.expected_phases.append({"name": "SPIN", "duration_sec": spin_dur, "type": "strict"})
                
                # Refill for the next rinse
                self.expected_phases.append({"name": "WATER_FILL", "duration_sec": times.get("water_fill_sec", 180), "type": "max_limit"})
                
                # Actual Rinse Wash (labeled RINSE_1, RINSE_2 in LogicMonitor)
                self.expected_phases.append({"name": f"RINSE_{i}", "duration_sec": times.get("rinse_wash_sec", 240), "type": "strict"})

        # 4. Final Spin
        final_spin_sec = times.get("final_spin_sec", 0)
        if final_spin_sec is not None and final_spin_sec > 0:
            self.expected_phases.append({"name": "DRAIN", "duration_sec": times.get("drain_sec", 120), "type": "max_limit"})
            self.expected_phases.append({"name": "SPIN_PAUSE", "duration_sec": 150, "type": "strict"})
            self.expected_phases.append({"name": "SPIN", "duration_sec": final_spin_sec, "type": "strict"})

        # 5. Anti-Wrinkle (Optional but standard in some courses, Rinse part2.png)
        # 120s pulsator activity to prevent clothes from sticking to the tub
        if final_spin_sec > 0:
            self.expected_phases.append({"name": "ANTI_WRINKLE", "duration_sec": 120, "type": "max_limit"})

        total_dur = sum(p["duration_sec"] for p in self.expected_phases)
        m, s = divmod(int(total_dur), 60)
        self.log_callback(f"✅ SequenceValidator: Program '{program_name}' LEV-{level} loaded. Total duration: {m}m {s}s. Steps: {len(self.expected_phases)}")
        self._emit_status()


    def evaluate_state(self, actual_phase):
        if self.is_failed or not self.expected_phases or self.current_step_index >= len(self.expected_phases):
            return

        expected_step = self.expected_phases[self.current_step_index]
        expected_phase_name = expected_step["name"]

        # --- PHASE SYNCHRONIZATION (The "Precision Sync" Guard) ---
        # Only jump if the machine is CLEARLY in a future phase and NOT in the current one.
        if actual_phase != expected_phase_name and actual_phase != 'IDLE':
            for i in range(self.current_step_index + 1, len(self.expected_phases)):
                if actual_phase == self.expected_phases[i]["name"]:
                    # Safety check: Don't jump over a WASH or SPIN if we just started
                    missed = [p["name"] for p in self.expected_phases[self.current_step_index:i]]
                    self.log_callback(f"⚠️ SYNC: Machine skipped {missed} -> Moving to {actual_phase}")
                    self.current_step_index = i
                    self.time_in_current_phase = 0
                    # Update expected pointers after jump
                    expected_step = self.expected_phases[self.current_step_index]
                    expected_phase_name = expected_step["name"]
                    break
        
        # Tracking Time (1 tick = 100ms)
        if actual_phase == expected_phase_name:
            self.time_in_current_phase += 1
            
        time_sec = self.time_in_current_phase / 10.0

        # Phase Transition Logic (Detecting when a phase ENDS)
        if actual_phase != self.last_phase:
            # If the machine just FINISHED the expected phase
            if self.last_phase == expected_phase_name:
                target_time = expected_step["duration_sec"]
                
                # Check timing accuracy
                if expected_step["type"] == "strict":
                    if abs(time_sec - target_time) > self.TOLERANCE_SEC:
                        self._trigger_fail(f"Phase '{expected_phase_name}' took {time_sec:.1f}s, expected {target_time}s (±{self.TOLERANCE_SEC}s).", target_time, time_sec)
                        return
                elif expected_step["type"] == "max_limit":
                    if time_sec > target_time + self.TOLERANCE_SEC:
                        self._trigger_fail(f"Phase '{expected_phase_name}' took {time_sec:.1f}s, exceeded max limit of {target_time}s.", target_time, time_sec)
                        return

                # Record PASS and move to next step
                self._record_pass(expected_phase_name, target_time, time_sec)
                self.current_step_index += 1
                self.time_in_current_phase = 0
                
            # Update last_phase for next tick
            self.last_phase = actual_phase

        # Continuous over-run check (while still in the phase)
        if actual_phase == expected_phase_name:
            target_time = expected_step["duration_sec"]
            if expected_step["type"] == "strict" and time_sec > target_time + self.TOLERANCE_SEC:
                 self._trigger_fail(f"Phase '{expected_phase_name}' time exceeded! Running for {time_sec:.1f}s (Target: {target_time}s).", target_time, time_sec)
                 return

        self._emit_status()

    def _trigger_fail(self, reason, expected=None, actual=None):
        self.is_failed = True
        msg = f"❌ SEQUENCE FAIL: {reason}"
        self.log_callback(msg)
        self.record_callback("Sequence Validation", "FAIL", msg, expected, actual)
        self._emit_status()

    def _record_pass(self, phase, expected_time, actual_time):
        msg = f"✅ SEQUENCE PASS: {phase} completed in {actual_time:.1f}s (Expected: {expected_time}s)"
        self.log_callback(msg)
        self.record_callback(f"Phase Validator: {phase}", "PASS", msg, expected_time, actual_time)

    def _emit_status(self):
        if not self.expected_phases or self.current_step_index >= len(self.expected_phases):
            status = {"expected_phase": "Finished/Idle", "time_left": 0, "status": "FAIL" if self.is_failed else "IDLE"}
        else:
            expected_step = self.expected_phases[self.current_step_index]
            # 1. Current phase time left
            total_left = max(0, expected_step["duration_sec"] - (self.time_in_current_phase / 10.0))
            # 2. Add all future phases durations
            for i in range(self.current_step_index + 1, len(self.expected_phases)):
                total_left += self.expected_phases[i]["duration_sec"]
                
            status = {
                "expected_phase": expected_step["name"],
                "time_left": total_left,
                "status": "FAIL" if self.is_failed else "RUNNING"
            }
        self.validation_status.emit(status)

    def reset(self):
        self.current_step_index = 0
        self.time_in_current_phase = 0
        self.last_phase = 'IDLE'
        self.is_failed = False
        self.expected_phases = []
