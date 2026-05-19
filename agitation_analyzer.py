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
    "Tub Clean": { "on": 1.5, "off": 1.0 },
    "MU": { "on": 0.3, "off": 1.2 },
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

    # 3. Calculate stroke metrics and calibrate physical delays
    # Compensation math: 0.15s software lag + 0.25s VFD deceleration = 0.4s total stretch offset
    calibrated_strokes = []
    for idx, stroke in enumerate(strokes):
        start_row = stroke[0][0]
        end_row = stroke[-1][0]
        measured_on = (end_row - start_row + 1) * 0.1
        
        # Calculate pause after this stroke
        measured_off = None
        if idx < len(strokes) - 1:
            next_start_row = strokes[idx+1][0][0]
            measured_off = (next_start_row - end_row - 1) * 0.1
            
        # Calibration Formula:
        # Optimized for halved DAQ buffer size (0.25s VFD deceleration delay, 0s OFF-time stretch)
        elec_on = max(0.1, round(measured_on - 0.25, 2))
        elec_off = round(measured_off, 2) if measured_off is not None else None
        
        # Check active valves during the stroke to classify intermediate fill (M3)
        cold_avg = sum(r[3] for r in stroke) / len(stroke)
        hot_avg = sum(r[4] for r in stroke) / len(stroke)
        is_water_active = (cold_avg > 1.0 or hot_avg > 1.0)
        
        calibrated_strokes.append({
            "start_row": start_row,
            "end_row": end_row,
            "measured_on": measured_on,
            "measured_off": measured_off,
            "elec_on": elec_on,
            "elec_off": elec_off,
            "is_water_active": is_water_active,
            "peak_rpm": max(r[2] for r in stroke)
        })

    # 4. Perform Verifications (M1, M2, M3, M4, MU, Anti-Wrinkle)
    TOLERANCE = 0.25  # 250 milliseconds HIL standard tolerance
    
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
        "Row_Index": m1_rows[0][0] if m1_rows else 1,
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
            aw_strokes.append(s)
        # MU pattern has very short ON (< 0.4s electrical)
        elif s["elec_on"] <= 0.35:
            mu_strokes.append(s)
        # M3 pattern has active water valves during the stroke
        elif s["is_water_active"]:
            m3_strokes.append(s)
        # M2 is active in the first 60 seconds after agitation starts
        elif (s["start_row"] * 0.1 - first_stroke_time) <= 60.0:
            m2_strokes.append(s)
        # M4 is the rest of the main wash
        else:
            m4_strokes.append(s)

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
        # ── M2: Initial Wash Agitation Validation ──
        expected_on, expected_off = spec_set["m2"]
        if m2_strokes:
            on_times = [s["elec_on"] for s in m2_strokes]
            off_times = [s["elec_off"] for idx, s in enumerate(m2_strokes) if idx < len(m2_strokes) - 1 and s["elec_off"] is not None]
            
            avg_on = round(np.mean(on_times), 2) if on_times else 0.0
            avg_off = round(np.mean(off_times), 2) if off_times else 0.0
            
            failures = []
            for idx, s in enumerate(m2_strokes):
                if abs(s["elec_on"] - expected_on) > TOLERANCE:
                    failures.append(f"Row {s['start_row']}: ON {s['elec_on']}s (exp {expected_on}s)")
                if idx < len(m2_strokes) - 1 and s["elec_off"] is not None and abs(s["elec_off"] - expected_off) > TOLERANCE:
                    failures.append(f"Row {s['end_row']}: OFF {s['elec_off']}s (exp {expected_off}s)")
                    
            m2_status = "FAIL" if failures else "PASS"
            if failures:
                m2_evidence = (
                    f"BUG: Initial wash agitation timing mismatch detected! ON Avg was {avg_on}s and OFF Avg was {avg_off}s. "
                    f"Anomalies found at: {', '.join(failures[:3])}. "
                    f"EXPECTED: ON: {expected_on}s and OFF: {expected_off}s. "
                    f"SOURCE: Sharp HIL Specification Sheet (Course: {program_name}, Level: LEV-{level_key}, Movement: M2)."
                )
            else:
                m2_evidence = f"Verified {len(m2_strokes)} initial agitation cycles. Avg ON: {avg_on}s / Avg OFF: {avg_off}s. All cycles match specification within strict ±0.25s HIL safety tolerance."
                
            verifications.append({
                "Row_Index": m2_strokes[0]["start_row"],
                "Test_Name": f"M2 Initial Wash Agitation (Level {level_key})",
                "Status": m2_status,
                "Expected_Sec": f"ON: {expected_on}s | OFF: {expected_off}s",
                "Actual_Sec": f"ON: {avg_on}s | OFF: {avg_off}s",
                "Technical_Evidence": m2_evidence
            })
        else:
            verifications.append({
                "Row_Index": 1,
                "Test_Name": f"M2 Initial Wash Agitation (Level {level_key})",
                "Status": "FAIL",
                "Expected_Sec": f"ON: {expected_on}s | OFF: {expected_off}s",
                "Actual_Sec": "ON: 0.0s | OFF: 0.0s",
                "Technical_Evidence": (
                    f"BUG: Dead Motor! No wash agitation strokes detected during the M2 Initial Wash phase. "
                    f"EXPECTED: Motor should agitate with ON: {expected_on}s / OFF: {expected_off}s. "
                    f"SOURCE: Sharp HIL Specification Sheet (Course: {program_name}, Level: LEV-{level_key}, Movement: M2)."
                )
            })

        # ── M3: Intermediate Agitation (2nd Water Supply) Validation ──
        expected_on, expected_off = spec_set["m3"]
        if m3_strokes:
            on_times = [s["elec_on"] for s in m3_strokes]
            off_times = [s["elec_off"] for idx, s in enumerate(m3_strokes) if idx < len(m3_strokes) - 1 and s["elec_off"] is not None]
            
            avg_on = round(np.mean(on_times), 2) if on_times else 0.0
            avg_off = round(np.mean(off_times), 2) if off_times else 0.0
            
            failures = []
            for idx, s in enumerate(m3_strokes):
                if abs(s["elec_on"] - expected_on) > TOLERANCE:
                    failures.append(f"Row {s['start_row']}: ON {s['elec_on']}s")
                if idx < len(m3_strokes) - 1 and s["elec_off"] is not None and abs(s["elec_off"] - expected_off) > TOLERANCE:
                    failures.append(f"Row {s['end_row']}: OFF {s['elec_off']}s")
                    
            m3_status = "FAIL" if failures else "PASS"
            if failures:
                m3_evidence = (
                    f"BUG: Intermediate water supply agitation timing mismatch detected! ON Avg was {avg_on}s and OFF Avg was {avg_off}s. "
                    f"Anomalies found at: {', '.join(failures[:3])}. "
                    f"EXPECTED: ON: {expected_on}s and OFF: {expected_off}s. "
                    f"SOURCE: Sharp HIL Specification Sheet (Course: {program_name}, Level: LEV-{level_key}, Movement: M3)."
                )
            else:
                m3_evidence = f"Verified {len(m3_strokes)} intermediate cycles during water supply. Avg ON: {avg_on}s / Avg OFF: {avg_off}s. All intermediate fill agitation cycles match specification."
                
            verifications.append({
                "Row_Index": m3_strokes[0]["start_row"],
                "Test_Name": f"M3 Intermediate Agitation (Level {level_key})",
                "Status": m3_status,
                "Expected_Sec": f"ON: {expected_on}s | OFF: {expected_off}s",
                "Actual_Sec": f"ON: {avg_on}s | OFF: {avg_off}s",
                "Technical_Evidence": m3_evidence
            })
        else:
            valves_active = any((r[3] > 4.0 or r[4] > 4.0) and r[0] > (strokes[0][0][0] if strokes else 0) for r in raw_data_log)
            if valves_active:
                verifications.append({
                    "Row_Index": 1,
                    "Test_Name": f"M3 Intermediate Agitation (Level {level_key})",
                    "Status": "FAIL",
                    "Expected_Sec": f"ON: {expected_on}s | OFF: {expected_off}s",
                    "Actual_Sec": "ON: 0.0s | OFF: 0.0s",
                    "Technical_Evidence": (
                        f"BUG: Dead Motor during intermediate water supply! Water valves were active, but no M3 agitation strokes were detected. "
                        f"EXPECTED: Motor should agitate with ON: {expected_on}s / OFF: {expected_off}s. "
                        f"SOURCE: Sharp HIL Specification Sheet (Course: {program_name}, Level: LEV-{level_key}, Movement: M3)."
                    )
                })

    # ── M4: Main Wash Agitation Validation ──
    expected_on, expected_off = spec_set["m4"]
    if m4_strokes:
        on_times = [s["elec_on"] for s in m4_strokes]
        off_times = [s["elec_off"] for idx, s in enumerate(m4_strokes) if idx < len(m4_strokes) - 1 and s["elec_off"] is not None]
        
        avg_on = round(np.mean(on_times), 2) if on_times else 0.0
        avg_off = round(np.mean(off_times), 2) if off_times else 0.0
        
        failures = []
        for idx, s in enumerate(m4_strokes):
            if abs(s["elec_on"] - expected_on) > TOLERANCE:
                failures.append(f"Row {s['start_row']}: ON {s['elec_on']}s")
            if idx < len(m4_strokes) - 1 and s["elec_off"] is not None and abs(s["elec_off"] - expected_off) > TOLERANCE:
                failures.append(f"Row {s['end_row']}: OFF {s['elec_off']}s")
                
        m4_status = "FAIL" if failures else "PASS"
        if failures:
            m4_evidence = (
                f"BUG: Main wash agitation timing mismatch detected! ON Avg was {avg_on}s and OFF Avg was {avg_off}s. "
                f"Anomalies found at: {', '.join(failures[:3])}. "
                f"EXPECTED: ON: {expected_on}s and OFF: {expected_off}s. "
                f"SOURCE: Sharp HIL Specification Sheet (Course: {program_name}, Level: LEV-{level_key}, Movement: M4)."
            )
        else:
            m4_evidence = f"Verified {len(m4_strokes)} main high-load wash cycles. Avg ON: {avg_on}s / Avg OFF: {avg_off}s. All main high-load wash cycles match specification."
            
        verifications.append({
            "Row_Index": m4_strokes[0]["start_row"],
            "Test_Name": f"M4 Main Wash Agitation (Level {level_key})",
            "Status": m4_status,
            "Expected_Sec": f"ON: {expected_on}s | OFF: {expected_off}s",
            "Actual_Sec": f"ON: {avg_on}s | OFF: {avg_off}s",
            "Technical_Evidence": m4_evidence
        })
    else:
        verifications.append({
            "Row_Index": 1,
            "Test_Name": f"M4 Main Wash Agitation (Level {level_key})",
            "Status": "FAIL",
            "Expected_Sec": f"ON: {expected_on}s | OFF: {expected_off}s",
            "Actual_Sec": "ON: 0.0s | OFF: 0.0s",
            "Technical_Evidence": (
                f"BUG: Dead Motor! No main wash agitation strokes detected during M4. "
                f"EXPECTED: Motor should agitate with ON: {expected_on}s / OFF: {expected_off}s. "
                f"SOURCE: Sharp HIL Specification Sheet (Course: {program_name}, Level: LEV-{level_key}, Movement: M4)."
            )
        })

    # ── MU: Unbalance Stir / Fragrance Agitation Validation ──
    expected_on, expected_off = TIMINGS["MU"]["on"], TIMINGS["MU"]["off"]
    if mu_strokes:
        on_times = [s["elec_on"] for s in mu_strokes]
        off_times = [s["elec_off"] for idx, s in enumerate(mu_strokes) if idx < len(mu_strokes) - 1 and s["elec_off"] is not None]
        
        avg_on = round(np.mean(on_times), 2) if on_times else 0.0
        avg_off = round(np.mean(off_times), 2) if off_times else 0.0
        
        failures = []
        for idx, s in enumerate(mu_strokes):
            if abs(s["elec_on"] - expected_on) > TOLERANCE:
                failures.append(f"Row {s['start_row']}: ON {s['elec_on']}s")
            if idx < len(mu_strokes) - 1 and s["elec_off"] is not None and abs(s["elec_off"] - expected_off) > TOLERANCE:
                failures.append(f"Row {s['end_row']}: OFF {s['elec_off']}s")
                
        mu_status = "FAIL" if failures else "PASS"
        if failures:
            mu_evidence = (
                f"BUG: Unbalance stir timing mismatch detected! ON Avg was {avg_on}s and OFF Avg was {avg_off}s. "
                f"Anomalies found at: {', '.join(failures[:3])}. "
                f"EXPECTED: ON: {expected_on}s and OFF: {expected_off}s. "
                f"SOURCE: Sharp HIL Specification Sheet (Course: {program_name}, Level: LEV-{level_key}, Movement: MU)."
            )
        else:
            mu_evidence = f"Verified {len(mu_strokes)} gentle unbalance stir / fragrance cycles. Avg ON: {avg_on}s / Avg OFF: {avg_off}s. All unbalance correction / fragrance agitation cycles match specification."
            
        verifications.append({
            "Row_Index": mu_strokes[0]["start_row"],
            "Test_Name": "MU Unbalance Stir / Fragrance Agitation",
            "Status": mu_status,
            "Expected_Sec": f"ON: {expected_on}s | OFF: {expected_off}s",
            "Actual_Sec": f"ON: {avg_on}s | OFF: {avg_off}s",
            "Technical_Evidence": mu_evidence
        })
    else:
        if spin_row_indices:
            verifications.append({
                "Row_Index": spin_row_indices[0],
                "Test_Name": "MU Unbalance Stir / Fragrance Agitation",
                "Status": "FAIL",
                "Expected_Sec": f"ON: {expected_on}s | OFF: {expected_off}s",
                "Actual_Sec": "ON: 0.0s | OFF: 0.0s",
                "Technical_Evidence": (
                    f"BUG: Dead Motor before spin! Spin was initiated, but no MU unbalance stir strokes were detected beforehand. "
                    f"EXPECTED: Motor should agitate with ON: {expected_on}s / OFF: {expected_off}s. "
                    f"SOURCE: Sharp HIL Specification Sheet (Course: {program_name}, Level: LEV-{level_key}, Movement: MU)."
                )
            })

    # ── Anti-Wrinkle Untangle Validation ──
    if aw_strokes:
        expected_on, expected_off = 0.8, 1.0
        on_times = [s["elec_on"] for s in aw_strokes]
        off_times = [s["elec_off"] for idx, s in enumerate(aw_strokes) if idx < len(aw_strokes) - 1 and s["elec_off"] is not None]
        
        avg_on = round(np.mean(on_times), 2) if on_times else 0.0
        avg_off = round(np.mean(off_times), 2) if off_times else 0.0
        
        failures = []
        for idx, s in enumerate(aw_strokes):
            if abs(s["elec_on"] - expected_on) > TOLERANCE:
                failures.append(f"Row {s['start_row']}: ON {s['elec_on']}s")
            if idx < len(aw_strokes) - 1 and s["elec_off"] is not None and abs(s["elec_off"] - expected_off) > TOLERANCE:
                failures.append(f"Row {s['end_row']}: OFF {s['elec_off']}s")
                
        aw_status = "FAIL" if failures else "PASS"
        if failures:
            aw_evidence = (
                f"BUG: Post-spin Anti-Wrinkle untangle timing mismatch detected! ON Avg was {avg_on}s and OFF Avg was {avg_off}s. "
                f"Anomalies found at: {', '.join(failures[:3])}. "
                f"EXPECTED: ON: {expected_on}s and OFF: {expected_off}s. "
                f"SOURCE: Sharp HIL Specification Sheet (Course: {program_name}, Level: LEV-{level_key}, Anti-Wrinkle Logic)."
            )
        else:
            aw_evidence = f"Verified {len(aw_strokes)} post-spin Anti-Wrinkle untangle cycles. Avg ON: {avg_on}s / Avg OFF: {avg_off}s. All Anti-Wrinkle untangle cycles match specification."
            
        verifications.append({
            "Row_Index": aw_strokes[0]["start_row"],
            "Test_Name": "Anti-Wrinkle Post-Spin Untangle Verification",
            "Status": aw_status,
            "Expected_Sec": f"ON: {expected_on}s | OFF: {expected_off}s",
            "Actual_Sec": f"ON: {avg_on}s | OFF: {avg_off}s",
            "Technical_Evidence": aw_evidence
        })

    return verifications
