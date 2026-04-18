import pandas as pd
import json

def extract_config():
    file_path = 'Sharp VE BLDC 11,13kg V0.xlsx'
    
    # 1. Extract Errors
    print("Extracting Errors...")
    df_errors = pd.read_excel(file_path, sheet_name='Errors')
    df_errors.dropna(how='all', inplace=True)
    df_errors.dropna(axis=1, how='all', inplace=True)
    
    errors_config = []
    
    for i in range(len(df_errors)):
        try:
            row = df_errors.iloc[i]
            error_name = str(row.iloc[0]).strip()
            error_code = str(row.iloc[1]).strip()
            detection = str(row.iloc[2]).strip()
            
            if error_code and error_code != 'nan' and error_code != 'Error Code':
                errors_config.append({
                    "code": error_code,
                    "name": error_name,
                    "detection_rules": detection
                })
        except Exception:
            continue
            
    # 2. Extract Course Timings for ALL Groups
    groups_to_extract = ['Course Group 1', 'Course Group 2', 'Course Group 3']
    programs_config = {}
    total_levels_extracted = 0
    
    for group_name in groups_to_extract:
        print(f"Extracting Timings from {group_name}...")
        course_timings = {}
        try:
            df_course = pd.read_excel(file_path, sheet_name=group_name)
            # Default lookup columns
            cw_col_idx = 11
            ccw_col_idx = 13
            # We look rows 3 to 20 for levels 1 to 10
            for idx in range(3, 20):
                try:
                    level = str(df_course.iloc[idx, 1]).strip()
                    if level and level.isdigit():
                        m2_cw = float(df_course.iloc[idx, cw_col_idx]) if pd.notnull(df_course.iloc[idx, cw_col_idx]) else 0.5
                        m2_ccw = float(df_course.iloc[idx, ccw_col_idx]) if pd.notnull(df_course.iloc[idx, ccw_col_idx]) else 0.5
                        course_timings[level] = {
                            "m2_cw_sec": m2_cw,
                            "m2_ccw_sec": m2_ccw
                        }
                        total_levels_extracted += 1
                except Exception:
                    pass
            programs_config[group_name] = course_timings
        except Exception as e:
            print(f"Could not extract {group_name}:", e)
            
    # Custom specs for un-grouped specialized programs
    programs_config['Tub Clean'] = {"1": {"m2_cw_sec": 1.5, "m2_ccw_sec": 1.5}}
    programs_config['Blanket'] = {"1": {"m2_cw_sec": 0.8, "m2_ccw_sec": 0.8}}
    programs_config['Quick'] = {"1": {"m2_cw_sec": 0.4, "m2_ccw_sec": 0.4}}
    programs_config['Fragrance Rinse Spin'] = {"1": {"m2_cw_sec": 0.0, "m2_ccw_sec": 0.0}}
        
    config = {
        "errors": errors_config,
        "programs": programs_config 
    }
    
    with open('wm_config.json', 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
        
    print(f"Extracted {len(errors_config)} errors and {total_levels_extracted} levels across groups successfully!")

if __name__ == '__main__':
    extract_config()
