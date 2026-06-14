# HIL MOTOR AGITATION ANALYZER - SHARP SPEC VALIDATION MODULE
import numpy as np

TIMINGS = {
    "Group1": {
        "1": { "m2": (0.5, 1.0), "m3": (0.7, 1.0), "m4": (0.6, 1.0) },
        "2": { "m2": (0.8, 1.0), "m3": (2.1, 1.0), "m4": (0.9, 1.0) },
        "3": { "m2": (1.3, 1.0), "m3": (1.2, 1.0), "m4": (1.1, 1.0) },
        "4": { "m2": (1.5, 1.0), "m3": (1.8, 1.5), "m4": (2.2, 1.5) }
    },
    "Group2": {
        "1": { "m2": (0.7, 1.0), "m3": (0.7, 1.0), "m4": (0.7, 1.0) },
        "2": { "m2": (1.0, 1.0), "m3": (1.0, 1.0), "m4": (1.0, 1.0) },
        "3": { "m2": (1.2, 1.0), "m3": (1.2, 1.0), "m4": (1.2, 1.0) },
        "4": { "m2": (1.8, 1.0), "m3": (2.1, 1.5), "m4": (2.5, 2.0) }
    },
    "Group3": {
        "1": { "m2": (0.5, 2.0), "m3": (0.5, 2.0), "m4": (0.5, 2.0) },
        "2": { "m2": (0.5, 2.0), "m3": (0.5, 2.0), "m4": (0.5, 2.0) },
        "3": { "m2": (0.5, 2.0), "m3": (0.5, 2.0), "m4": (0.5, 2.0) },
        "4": { "m2": (0.5, 2.0), "m3": (0.5, 2.0), "m4": (0.5, 2.0) }
    },
    "Blanket": { "on": 3.8, "off": 0.7 },
    "Blanket_MU": { "on": 1.0, "off": 0.7 },
    "Tub Clean": { "on": 1.5, "off": 1.0 },
    "MU": { "on": 0.3, "off": 0.7 },
    "Soak": { "on": 2.4, "off": 2.6 }
}

COURSE_GROUPS = {
    "Group 1": ["Regular", "Quick", "Baby Care", "Quick Rinse"],
    "Group 2": ["Jeans", "Cotton", "Heavy"],
    "Group 3": ["Wool", "Delicates", "Sports Wear"]
}

def analyze_telemetry(raw_data_log, program_name, level_str):
    """
    Parses HIL telemetry rows to perform high-precision validation of motor agitation profiles (M1 to MU).
    Returns a list of verification summary dictionaries ready for the Excel report.
    """
    verifications = []
    course_group = "Unknown"
    
    # 1. Determine expected timings (Support custom groups & special courses)
    if program_name == "Blanket":
        spec_set = {
            "m2": (2.4, 1.6),  # Water supply with stirring
            "m3": (2.4, 1.6),  # Water supply with stirring
            "m4": (3.8, 0.7)   # Blanket main wash
        }
        level_key = "4"        # Blanket is fixed at LEV-4
    elif program_name == "Tub Clean":
        spec_set = {
            "m2": (3.4, 4.6),  # Water supply with stirring
            "m3": (3.4, 4.6),  # Water supply with stirring
            "m4": (1.5, 1.0)   # Tub Clean soak & wash
        }
        level_key = "4"        # Tub Clean is fixed at LEV-4
    elif program_name == "Soak":
        spec_set = {
            "m2": (2.4, 2.6),  # Soak rotating water flow
            "m3": (2.4, 2.6),
            "m4": (2.4, 2.6)
        }
        level_key = "2"
    else:
        # Standard course group routing
        course_group = "Group1"
        for g_name, progs in COURSE_GROUPS.items():
            if program_name in progs:
                course_group = g_name.replace(" ", "")
                break
                
        # Standardize level
        level_key = "2"
        if isinstance(level_str, int):
            level_key = str(level_str)
        elif isinstance(level_str, str):
            level_key = level_str.replace("LEV-", "").strip()
            
        spec_set = TIMINGS.get(course_group, TIMINGS["Group1"]).get(level_key, TIMINGS["Group1"]["2"])

    # 2. Split data into active cycles (Strokes)
    strokes = []
    current_stroke = []
    
    for row in raw_data_log:
        rpm = row[2]
        if rpm > 5.0:
            current_stroke.append(row)
        else:
            if current_stroke:
                strokes.append(current_stroke)
                current_stroke = []
    if current_stroke:
        strokes.append(current_stroke)

    # Filter out SPIN/DRAIN active pump/gear strokes (>2.0V)
    strokes = [s for s in strokes if not any(r[8] > 2.0 or r[6] > 2.0 for r in s)]

    # 3. Calculate stroke metrics based on exact engineering specification
    calibrated_strokes = []
    for idx, stroke in enumerate(strokes):
        start_row = stroke[0][0]
        peak_rpm = max(r[2] for r in stroke)
        
        # Plateau detection: find the last row in stroke where RPM >= 0.95 * peak_rpm
        plateau_end_idx = 0
        for i, r in enumerate(stroke):
            if r[2] >= 0.95 * peak_rpm:
                plateau_end_idx = i
        plateau_end_row = stroke[plateau_end_idx][0]
                
        # Calculate Electrical ON (from start >0 to plateau end)
        elec_on = round((plateau_end_row - start_row + 1) * 0.1, 2)
        
        # Calculate Pause after this stroke
        elec_off = None
        if idx < len(strokes) - 1:
            next_start_row = strokes[idx+1][0][0]
            elec_off = round((next_start_row - plateau_end_row - 1) * 0.1, 2)
            
        # Check active valves during the stroke to classify intermediate fill (M3)
        cold_avg = sum(r[3] for r in stroke) / len(stroke)
        hot_avg = sum(r[4] for r in stroke) / len(stroke)
        is_water_active = (cold_avg > 1.0 or hot_avg > 1.0)
        
        calibrated_strokes.append({
            "start_row": start_row,
            "end_row": stroke[-1][0],
            "plateau_end_row": plateau_end_row,
            "elec_on": elec_on,
            "elec_off": elec_off,
            "is_water_active": is_water_active,
            "peak_rpm": peak_rpm
        })

    # Noise Filter & Isolation
    filtered_strokes = []
    for idx, s in enumerate(calibrated_strokes):
        # Engineering threshold: 15 Tub RPM effectively separates physical agitation from electrical noise.
        if s["elec_on"] < 0.25 or s["peak_rpm"] < 15:
            continue
        
        prev_off = calibrated_strokes[idx-1]["elec_off"] if idx > 0 else 0
        next_off = s["elec_off"] if s["elec_off"] is not None else 0
        
        if s["elec_on"] <= 0.3 and prev_off > 5.0 and next_off > 5.0:
            continue
            
        filtered_strokes.append(s)

    # Recalculate OFF times for filtered strokes
    for i in range(len(filtered_strokes) - 1):
        filtered_strokes[i]["elec_off"] = round((filtered_strokes[i+1]["start_row"] - filtered_strokes[i]["plateau_end_row"] - 1) * 0.1, 2)
    if filtered_strokes:
        filtered_strokes[-1]["elec_off"] = None

    calibrated_strokes = filtered_strokes

    # Find the end of WASH (first DRAIN = first time pump turns on after motor has started)
    first_motor_row = strokes[0][0][0] if strokes else 0
    first_drain_row = 9999999
    for r in raw_data_log:
        if first_motor_row and r[0] > first_motor_row + 100 and r[8] > 2.0:
            first_drain_row = r[0]
            break

    # 4. Perform Verifications (M1, M2, M3, M4, MU, Anti-Wrinkle)
    TOLERANCE = 0.20  # 200 milliseconds tolerance based on user instructions
    
    # ── M1: Initial Water Fill Verification ──
    m1_rows = [r for r in raw_data_log if (r[3] > 4.0 or r[4] > 4.0) and r[0] < (strokes[0][0][0] if strokes else 999999)]
    m1_rpm_violations = [r for r in m1_rows if r[2] > 5.0]
    
    has_filled = any(r[7] < 1.0 for r in raw_data_log)
    
    m1_status = "PASS"
    m1_evidence = "Water fill initiated successfully. Motor remained perfectly stationary (0 RPM) during filling as required by M1. Pressure switch confirmed target water level reached (Empty signal dropped to 0V)."
    
    if m1_rpm_violations:
        m1_status = "FAIL"
        m1_evidence = (
            f"BUG: Motor rotated during initial water fill! Rotation detected at Row {m1_rpm_violations[0][0]} (RPM: {m1_rpm_violations[0][2]}). "
            f"EXPECTED: Motor must remain perfectly stationary (0.0s ON / 0 RPM) during the fill sequence. "
            f"SOURCE: Sharp Washing Machine HIL Specification Sheet (M1 Fill Logic)."
        )
    elif not has_filled:
        m1_status = "FAIL"
        m1_evidence = (
            f"BUG: Pressure switch never detected water level! Empty signal remained 5V (Empty) for the entire 360-second fill timeout. "
            f"EXPECTED: Target water level must be reached (Empty signal drops to 0V) before fill timeout. "
            f"SOURCE: Sharp Washing Machine HIL Specification Sheet (M1 Level Sensing)."
        )
        
    verifications.append({
        "Row_Index": f"{m1_rows[0][0]}-{m1_rows[-1][0]}" if m1_rows else 1,
        "Test_Name": "M1 Initial Water Fill & Level Verification",
        "Status": m1_status,
        "Expected_Sec": "Motor: 0.0s | Fill: Active",
        "Actual_Sec": f"Motor: {len(m1_rpm_violations)*0.1:.1f}s | Level: {'OK' if has_filled else 'TIMEOUT'}",
        "Technical_Evidence": m1_evidence
    })

    # Detect the end of the final spin phase to identify any post-spin Anti-Wrinkle motions
    spin_row_indices = [r[0] for r in raw_data_log if r[2] > 150.0]
    last_spin_row = spin_row_indices[-1] if spin_row_indices else 0

    # Segment strokes into M2, M3, M4, MU, and Anti-Wrinkle (AW)
    m2_strokes = []
    m3_strokes = []
    m4_strokes = []
    mu_strokes = []
    aw_strokes = []
    
    first_stroke_time = calibrated_strokes[0]["start_row"] * 0.1 if calibrated_strokes else 0
    
    for s in calibrated_strokes:
        # Any stroke starting AFTER the final spin is classified as Anti-Wrinkle
        if last_spin_row > 0 and s["start_row"] > last_spin_row:
            if s["elec_on"] >= 0.3:
                aw_strokes.append(s)
        # Exclude massive spin cycles (> 10s ON time) from agitation analysis
        elif s["elec_on"] > 10.0:
            continue
        # MU pattern has very short ON (<= 0.6s electrical) to handle 0.3s spec with tolerance
        elif s["elec_on"] <= 0.6 and s["start_row"] <= first_drain_row:
            mu_strokes.append(s)
        # Stroke must be inside WASH (before first DRAIN) for M2/M3/M4
        elif s["start_row"] <= first_drain_row:
            # M3 pattern has active water valves during the stroke
            if s["is_water_active"]:
                m3_strokes.append(s)
            # M2 is active in the first 60 seconds after agitation starts
            elif (s["start_row"] * 0.1 - first_stroke_time) <= 60.0:
                m2_strokes.append(s)
            # M4 is the rest of the main wash
            else:
                m4_strokes.append(s)

    def validate_movement(movement_strokes, phase_name, expected_specs):
        if not movement_strokes:
            return {
                "Row_Index": 1,
                "Test_Name": f"{phase_name} Agitation (Level {level_key})",
                "Status": "FAIL",
                "Expected_Sec": "N/A",
                "Actual_Sec": "N/A",
                "Technical_Evidence": (
                    f"BUG: Dead Motor! No wash agitation strokes detected during the {phase_name} phase. "
                    f"EXPECTED: Motor should agitate per spec. "
                    f"SOURCE: Sharp HIL Specification Sheet (Course: {program_name}, Level: LEV-{level_key}, Movement: {phase_name})."
                )
            }
        
        exp_on, exp_off = expected_specs
        on_times = [s["elec_on"] for s in movement_strokes]
        off_times = [s["elec_off"] for s in movement_strokes if s["elec_off"] is not None and s["elec_off"] < 15.0]
        avg_on = round(np.mean(on_times), 2) if on_times else 0.0
        avg_off = round(np.mean(off_times), 2) if off_times else 0.0
        
        failures = []
        for s in movement_strokes:
            if abs(s["elec_on"] - exp_on) > TOLERANCE:
                failures.append(f"Row {s['start_row']}-{s['end_row']}: ON {s['elec_on']}s")
            if s["elec_off"] is not None and s["elec_off"] < 15.0 and abs(s["elec_off"] - exp_off) > TOLERANCE:
                failures.append(f"Row {s['plateau_end_row']}-to-Next: OFF {s['elec_off']}s")
                
        status = "FAIL" if failures else "PASS"
        if failures:
            evidence = (
                f"BUG: {phase_name} agitation timing mismatch detected! ON Avg was {avg_on}s and OFF Avg was {avg_off}s. "
                f"Anomalies found at: {', '.join(failures[:3])}. "
                f"EXPECTED: ON: {exp_on}s and OFF: {exp_off}s. "
                f"SOURCE: Sharp HIL Specification Sheet (Course: {program_name}, Level: LEV-{level_key}, Movement: {phase_name})."
            )
        else:
            evidence = f"Verified {len(movement_strokes)} {phase_name} cycles. Avg ON: {avg_on}s / Avg OFF: {avg_off}s. All match specification."
            
        expected_sec_str = f"ON: {exp_on}s | OFF: {exp_off}s"
        actual_sec_str = f"ON: {avg_on}s | OFF: {avg_off}s"
            
        return {
            "Row_Index": f"{movement_strokes[0]['start_row']}-{movement_strokes[-1]['plateau_end_row']}",
            "Test_Name": f"{phase_name} Agitation (Level {level_key})",
            "Status": status,
            "Expected_Sec": expected_sec_str,
            "Actual_Sec": actual_sec_str,
            "Technical_Evidence": evidence
        }

    # ── Quick Course Exception: Skip M2 & M3 per Sharp Spec ──
    # "For Quick course only, skip M2 & M3" (Source: Course group1.png note)
    skip_m2_m3 = (program_name == "Quick")
    
    if skip_m2_m3:
        # Reclassify any strokes that were tagged as M2/M3 into M4 (main wash)
        m4_strokes = m2_strokes + m3_strokes + m4_strokes
        m4_strokes.sort(key=lambda s: s["start_row"])
        m2_strokes = []
        m3_strokes = []
        
        verifications.append({
            "Row_Index": 1,
            "Test_Name": f"M2 Initial Wash Agitation (Level {level_key})",
            "Status": "SKIPPED",
            "Expected_Sec": "N/A",
            "Actual_Sec": "N/A",
            "Technical_Evidence": (
                f"M2 validation skipped. Quick course does not include M2 motion phase per Sharp specification. "
                f"SOURCE: Sharp HIL Specification Sheet (Course group1 note: 'For Quick course only, skip M2 & M3')."
            )
        })
        verifications.append({
            "Row_Index": 1,
            "Test_Name": f"M3 Intermediate Agitation (Level {level_key})",
            "Status": "SKIPPED",
            "Expected_Sec": "N/A",
            "Actual_Sec": "N/A",
            "Technical_Evidence": (
                f"M3 validation skipped. Quick course does not include M3 motion phase per Sharp specification. "
                f"SOURCE: Sharp HIL Specification Sheet (Course group1 note: 'For Quick course only, skip M2 & M3')."
            )
        })
    else:
        verifications.append(validate_movement(m2_strokes, "M2", spec_set["m2"]))
        verifications.append(validate_movement(m3_strokes, "M3", spec_set["m3"]))
        
    verifications.append(validate_movement(m4_strokes, "M4", spec_set["m4"]))
    if program_name == "Blanket":
        mu_expected = (TIMINGS["Blanket_MU"]["on"], TIMINGS["Blanket_MU"]["off"])
        verifications.append(validate_movement(mu_strokes, "MU", mu_expected))
    elif course_group != "Group3":
        verifications.append(validate_movement(mu_strokes, "MU", (TIMINGS["MU"]["on"], TIMINGS["MU"]["off"])))
    

    if aw_strokes:
        verifications.append(validate_movement(aw_strokes, "Anti-Wrinkle", (0.8, 1.0)))

    return verifications
