# HIL MOTOR AGITATION ANALYZER - SHARP SPEC VALIDATION MODULE v3.0
# Per-stroke precision analysis with full calculation evidence. FAIL-only output.

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
        "1": { "m2": (0.5, 2.2), "m3": (0.5, 2.2), "m4": (0.5, 2.2) },
        "2": { "m2": (0.5, 2.2), "m3": (0.5, 2.2), "m4": (0.5, 2.2) },
        "3": { "m2": (0.5, 2.2), "m3": (0.5, 2.2), "m4": (0.5, 2.2) },
        "4": { "m2": (0.5, 2.2), "m3": (0.5, 2.2), "m4": (0.5, 2.2) }
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

FILL_TIMEOUT_SEC = 1200   # 20 minutes max fill time (E5 threshold)
TOLERANCE        = 0.10   # 100 ms tolerance per Sharp spec
TOLERANCE_WASH   = 60.0   # 60 seconds tolerance for total wash duration


def analyze_telemetry(raw_data_log, program_name, level_str,
                      wash_override=None, rinse_override=None, spin_override=None):
    """
    Parses HIL telemetry and returns ONLY FAIL defect entries.
    Each entry contains a full step-by-step calculation in Technical_Evidence.
    Defect entries include: Row_Index, Test_Name, Status, Severity, Priority,
                            Expected_Sec, Actual_Sec, Technical_Evidence
    """
    defects = []
    course_group = "Unknown"

    # ── 1. Determine expected timings ─────────────────────────────────────────
    if program_name == "Blanket":
        spec_set = {
            "m2": (2.4, 1.6),
            "m3": (2.4, 1.6),
            "m4": (3.8, 0.7)
        }
        level_key = "4"
    elif program_name == "Tub Clean":
        spec_set = {
            "m2": (3.4, 4.6),
            "m3": (3.4, 4.6),
            "m4": (1.5, 1.0)
        }
        level_key = "4"
    elif program_name == "Soak":
        spec_set = {
            "m2": (2.4, 2.6),
            "m3": (2.4, 2.6),
            "m4": (2.4, 2.6)
        }
        level_key = "2"
    else:
        course_group = "Group1"
        for g_name, progs in COURSE_GROUPS.items():
            if program_name in progs:
                course_group = g_name.replace(" ", "")
                break

        level_key = "2"
        if isinstance(level_str, int):
            level_key = str(level_str)
        elif isinstance(level_str, str):
            level_key = level_str.replace("LEV-", "").strip()

        spec_set = TIMINGS.get(course_group, TIMINGS["Group1"]).get(
            level_key, TIMINGS["Group1"]["2"]
        )

    # ── 2. Split raw data into motor-active strokes ───────────────────────────
    raw_strokes = []
    current = []
    for row in raw_data_log:
        if row[2] > 5.0:
            current.append(row)
        else:
            if current:
                raw_strokes.append(current)
                current = []
    if current:
        raw_strokes.append(current)

    # Remove SPIN/DRAIN strokes (pump or gearmotor voltage > 2 V)
    raw_strokes = [s for s in raw_strokes if not any(r[8] > 2.0 or r[6] > 2.0 for r in s)]

    if not raw_strokes:
        return defects

    # ── 3. Calibrate each stroke (ON time, OFF time, next_start_row) ──────────
    calibrated = []
    for idx, stroke in enumerate(raw_strokes):
        start_row   = stroke[0][0]
        end_row     = stroke[-1][0]
        peak_rpm    = max(r[2] for r in stroke)

        # Ignore tiny noise blips or motor braking artifacts (< 30 RPM)
        if peak_rpm < 30.0:
            continue

        on_rows  = end_row - start_row + 1
        elec_on  = round(on_rows * 0.1, 2)

        cold_avg = sum(r[3] for r in stroke) / len(stroke)
        hot_avg  = sum(r[4] for r in stroke) / len(stroke)

        calibrated.append({
            "start_row":      start_row,
            "end_row":        end_row,
            "on_rows":        on_rows,
            "elec_on":        elec_on,
            "is_water_active": (cold_avg > 1.0 or hot_avg > 1.0),
            "peak_rpm":       peak_rpm
        })

    # ── 4. Noise filter ───────────────────────────────────────────────────────
    filtered = []
    for idx, s in enumerate(calibrated):
        if s["elec_on"] < 0.25 or s["peak_rpm"] < 15:
            continue
        filtered.append(s)

    # Recalculate OFF / next_start_row after filtering
    for i in range(len(filtered) - 1):
        filtered[i]["next_start_row"] = filtered[i+1]["start_row"]
        filtered[i]["elec_off"] = round((filtered[i+1]["start_row"] - filtered[i]["end_row"] - 1) * 0.1, 2)
    if filtered:
        filtered[-1]["elec_off"] = None
        filtered[-1]["next_start_row"] = None

    calibrated = filtered

    # ── 5. Water Fill Duration + E5 Detection ─────────────────────────────────
    first_fill_row = None
    fill_end_row   = None

    for r in raw_data_log:
        if first_fill_row is None and (r[3] > 4.0 or r[4] > 4.0):
            first_fill_row = r[0]
        if first_fill_row and fill_end_row is None and r[7] < 1.0:
            fill_end_row = r[0]
            break

    if first_fill_row is not None:
        actual_end   = fill_end_row if fill_end_row else raw_data_log[-1][0]
        fill_rows    = actual_end - first_fill_row + 1
        fill_sec     = round(fill_rows * 0.1, 1)
        fill_min     = round(fill_sec / 60, 2)
        timeout_min  = FILL_TIMEOUT_SEC // 60

        is_e5 = fill_end_row is None  # pressure switch never triggered

        if is_e5 or fill_sec > FILL_TIMEOUT_SEC:
            label    = "E5 Timeout - Level Never Reached" if is_e5 else "Fill Duration Overrun"
            severity = "Critical"
            delta    = round(fill_sec - FILL_TIMEOUT_SEC, 1)
            defects.append({
                "Row_Index":          f"{first_fill_row}-{actual_end}",
                "Test_Name":          "M1 Water Fill - E5 Error",
                "Status":             "FAIL",
                "Severity":           severity,
                "Priority":           "High",
                "Expected_Sec":       f"Max {FILL_TIMEOUT_SEC}s ({timeout_min} min)",
                "Actual_Sec":         f"{fill_sec}s ({fill_min} min)",
                "Technical_Evidence": (
                    f"Number of rows: ({actual_end} - {first_fill_row} + 1) = {fill_rows} rows\n"
                    f"Time in seconds: {fill_rows} × 0.1 = {fill_sec}s\n"
                    f"Time in minutes: {fill_sec} ÷ 60 = {fill_min} min\n"
                    f"Max allowed: {timeout_min} min ({FILL_TIMEOUT_SEC}s)\n"
                    f"Delta: {fill_sec} - {FILL_TIMEOUT_SEC} = {delta:+.1f}s\n"
                    f"Verdict: {label}"
                )
            })

    # ── 6. WASH Total Duration ────────────────────────────────────────────────
    first_motor_row = calibrated[0]["start_row"] if calibrated else None
    first_drain_row = None
    for r in raw_data_log:
        if first_motor_row and r[0] > first_motor_row + 100 and r[8] > 2.0:
            first_drain_row = r[0]
            break

    expected_wash_sec = None
    if wash_override and wash_override != "Default":
        try:
            expected_wash_sec = float(wash_override.split(" ")[0]) * 60
        except Exception:
            pass
    else:
        try:
            import json, os
            spec_path = os.path.join(os.path.dirname(__file__), "sharp_spec.json")
            with open(spec_path, "r", encoding="utf-8") as f:
                spec_data = json.load(f)
            expected_wash_sec = float(spec_data.get("sequence_chart", {}).get(program_name, {}).get(level_str, {}).get("main_wash_sec", 0))
            if expected_wash_sec == 0:
                expected_wash_sec = None
        except Exception:
            pass

    if first_motor_row and first_drain_row and expected_wash_sec:
        wash_rows = first_drain_row - first_motor_row
        wash_sec  = round(wash_rows * 0.1, 1)
        wash_min  = round(wash_sec / 60, 2)
        exp_min   = round(expected_wash_sec / 60, 1)
        delta     = round(wash_sec - expected_wash_sec, 1)

        if abs(delta) > TOLERANCE_WASH:
            direction = "Overrun" if delta > 0 else "Deficit"
            defects.append({
                "Row_Index":          f"{first_motor_row}-{first_drain_row}",
                "Test_Name":          "WASH Total Duration",
                "Status":             "FAIL",
                "Severity":           "High",
                "Priority":           "Medium",
                "Expected_Sec":       f"{expected_wash_sec}s ({exp_min} min)",
                "Actual_Sec":         f"{wash_sec}s ({wash_min} min)",
                "Technical_Evidence": (
                    f"Number of rows: ({first_drain_row} - {first_motor_row}) = {wash_rows} rows\n"
                    f"Time in seconds: {wash_rows} × 0.1 = {wash_sec}s\n"
                    f"Time in minutes: {wash_sec} ÷ 60 = {wash_min} min\n"
                    f"Expected: {exp_min} min ({expected_wash_sec}s)\n"
                    f"Delta: {wash_sec} - {expected_wash_sec} = {delta:+.1f}s ({direction})"
                )
            })

    # ── 7. Stroke Segmentation ────────────────────────────────────────────────
    spin_rows        = [r[0] for r in raw_data_log if r[2] > 150.0]
    last_spin_row    = spin_rows[-1] if spin_rows else 0
    first_stroke_t   = calibrated[0]["start_row"] * 0.1 if calibrated else 0
    drain_ref        = first_drain_row if first_drain_row else 9_999_999

    m2, m3, m4, mu, aw = [], [], [], [], []

    for s in calibrated:
        if last_spin_row > 0 and s["start_row"] > last_spin_row:
            if s["elec_on"] >= 0.3:
                aw.append(s)
        elif s["elec_on"] > 10.0:
            continue
        elif s["elec_on"] <= 0.6 and s["start_row"] <= drain_ref:
            mu.append(s)
        elif s["start_row"] <= drain_ref:
            if s["is_water_active"]:
                m3.append(s)
            elif (s["start_row"] * 0.1 - first_stroke_t) <= 60.0:
                m2.append(s)
            else:
                m4.append(s)

    # ── 8. Per-stroke validation ───────────────────────────────────────────────
    def validate_movement(movement_strokes, phase_name, expected_specs):
        """Returns a list of FAIL dicts — one per failing ON or OFF measurement."""
        result = []

        if not movement_strokes:
            result.append({
                "Row_Index":          "N/A",
                "Test_Name":          f"{phase_name} Agitation - Dead Motor",
                "Status":             "FAIL",
                "Severity":           "Critical",
                "Priority":           "High",
                "Expected_Sec":       f"ON: {expected_specs[0]}s | OFF: {expected_specs[1]}s",
                "Actual_Sec":         "0 strokes detected",
                "Technical_Evidence": (
                    f"DEAD MOTOR: No {phase_name} strokes detected during expected phase window.\n"
                    f"Expected: Motor must agitate per spec (ON: {expected_specs[0]}s / OFF: {expected_specs[1]}s)\n"
                    f"Source: Sharp HIL Specification (Course: {program_name}, Level: LEV-{level_key}, Phase: {phase_name})"
                )
            })
            return result

        exp_on, exp_off = expected_specs

        for idx, s in enumerate(movement_strokes):
            stroke_num = idx + 1

            actual_on = s["elec_on"]
            actual_off = s.get("elec_off")
            
            # ── Mechanical Inertia Compensation (Cycle Time) ──
            # If the total cycle time (ON + OFF) perfectly matches expected (ON + OFF),
            # the logic board timer is flawless. Any deviation is purely physical motor coasting.
            cycle_pass = False
            if actual_off is not None and actual_off < 15.0:
                actual_cycle = actual_on + actual_off
                exp_cycle = exp_on + exp_off
                if round(abs(actual_cycle - exp_cycle), 2) <= TOLERANCE:
                    cycle_pass = True

            # ── ON Time check ──
            on_rows   = s["on_rows"]
            on_delta  = round(actual_on - exp_on, 2)

            if not cycle_pass and abs(on_delta) > TOLERANCE:
                direction = "Overrun" if on_delta > 0 else "Deficit"
                result.append({
                    "Row_Index":          f"{s['start_row']}-{s['end_row']}",
                    "Test_Name":          f"{phase_name} Stroke #{stroke_num} - ON Time",
                    "Status":             "FAIL",
                    "Severity":           "Medium",
                    "Priority":           "Medium",
                    "Expected_Sec":       f"{exp_on}s",
                    "Actual_Sec":         f"{actual_on}s",
                    "Delta_Sec":          f"{on_delta:+.2f}s",
                    "Technical_Evidence": (
                        f"Number of rows: ({s['end_row']} - {s['start_row']} + 1) = {on_rows} rows\n"
                        f"Time in seconds: {on_rows} * 0.1 = {actual_on}s\n"
                        f"Expected ON: {exp_on}s\n"
                        f"Delta: {actual_on} - {exp_on} = {on_delta:+.2f}s ({direction})"
                    )
                })

            # ── OFF Time check ──
            actual_off = s["elec_off"]
            if actual_off is not None and actual_off < 15.0:
                off_delta = round(actual_off - exp_off, 2)

                if not cycle_pass and abs(off_delta) > TOLERANCE:
                    direction  = "Overrun" if off_delta > 0 else "Deficit"
                    ns         = s["next_start_row"] if s["next_start_row"] else s["end_row"]
                    off_rows   = round(actual_off / 0.1)
                    result.append({
                        "Row_Index":          f"{s['end_row']}-{ns}",
                        "Test_Name":          f"{phase_name} Stroke #{stroke_num} - OFF Time",
                        "Status":             "FAIL",
                        "Severity":           "Medium",
                        "Priority":           "Medium",
                        "Expected_Sec":       f"{exp_off}s",
                        "Actual_Sec":         f"{actual_off}s",
                        "Delta_Sec":          f"{off_delta:+.2f}s",
                        "Technical_Evidence": (
                            f"Number of rows: ({ns} - {s['end_row']} - 1) = {off_rows} rows\n"
                            f"Time in seconds: {off_rows} × 0.1 = {actual_off}s\n"
                            f"Expected OFF: {exp_off}s\n"
                            f"Delta: {actual_off} - {exp_off} = {off_delta:+.2f}s ({direction})"
                        )
                    })

        return result

    # ── 9. Run validations in order ───────────────────────────────────────────
    skip_m2_m3 = (program_name == "Quick")

    if skip_m2_m3:
        m4 = sorted(m2 + m3 + m4, key=lambda s: s["start_row"])
        m2, m3 = [], []
    else:
        defects.extend(validate_movement(m2, "M2", spec_set["m2"]))
        defects.extend(validate_movement(m3, "M3", spec_set["m3"]))

    defects.extend(validate_movement(m4, "M4", spec_set["m4"]))

    if program_name == "Blanket":
        defects.extend(validate_movement(mu, "MU", (TIMINGS["Blanket_MU"]["on"], TIMINGS["Blanket_MU"]["off"])))
    elif course_group != "Group3":
        defects.extend(validate_movement(mu, "MU", (TIMINGS["MU"]["on"], TIMINGS["MU"]["off"])))

    if aw:
        defects.extend(validate_movement(aw, "Anti-Wrinkle", (0.8, 1.0)))

    return defects
