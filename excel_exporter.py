# SHARP HIL REPORTING MODULE - VERSION 2.1
import pandas as pd
import xlsxwriter
from datetime import datetime

class ExcelExporter:
    def __init__(self, filename):
        self.filename = filename

    def export(self, raw_data, summary_data):
        if isinstance(summary_data, dict) and 'test_cases' in summary_data:
            summary_data = summary_data['test_cases']
            
        transformed_raw = []
        for row in raw_data:
            # row is: [row_idx, timestamp, motor_rpm, cold_v, hot_v, softener, gearmotor, empty, pump, door]
            row_idx = row[0]
            telemetry = row[2:]
            
            # Precise elapsed time calculations for 10Hz HIL signals (Zero-Jitter)
            total_deciseconds = row_idx - 1
            h = total_deciseconds // 36000
            remaining = total_deciseconds % 36000
            m = remaining // 600
            remaining = remaining % 600
            s = remaining // 10
            ms = (remaining % 10) / 10.0  # Deciseconds as float fraction (0.0, 0.1, 0.2 ... 0.9)
            
            transformed_row = [row_idx, h, m, s, ms] + telemetry
            transformed_raw.append(transformed_row)

        columns_raw = [
            "Row_Index", "H", "Min", "Sec", "ms", "Motor_RPM", "Cold_V", "Hot_V",
            "Softener", "GearMotor", "Empty", "Pump", "Door"
        ]
        df_raw = pd.DataFrame(transformed_raw, columns=columns_raw)
        
        columns_summary = ["Row_Index", "Test_Name", "Status", "Expected_Sec", "Actual_Sec", "Technical_Evidence"]
        df_summary = pd.DataFrame(summary_data)

        with pd.ExcelWriter(self.filename, engine='xlsxwriter') as writer:
            df_raw.to_excel(writer, sheet_name="Raw_Telemetry", index=False)
            
            workbook = writer.book
            worksheet_summary = workbook.add_worksheet('Analysis_Summary')
            
            # --- Formats ---
            header_format = workbook.add_format({
                'bold': True, 'font_size': 16, 
                'bg_color': '#0052CC', 'font_color': 'white', 
                'align': 'center', 'valign': 'vcenter',
                'border': 1
            })
            stat_header_format = workbook.add_format({'bold': True, 'font_size': 11, 'bg_color': '#F4F7F9'})
            wrap_format = workbook.add_format({'text_wrap': True, 'valign': 'top', 'border': 1})
            pass_format = workbook.add_format({'bg_color': '#C6EFCE', 'font_color': '#006100', 'bold': True, 'border': 1, 'align': 'center'})
            fail_format = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006', 'bold': True, 'border': 1, 'align': 'center'})
            skipped_format = workbook.add_format({'bg_color': '#D6E4F0', 'font_color': '#1F4E79', 'bold': True, 'border': 1, 'align': 'center'})
            warning_format = workbook.add_format({'bg_color': '#FFF2CC', 'font_color': '#7F6000', 'bold': True, 'border': 1, 'align': 'center'})
            default_format = workbook.add_format({'valign': 'top', 'border': 1})
            
            # --- Write Header Stats ---
            worksheet_summary.merge_range('A1:F1', 'Sharp Automated Software Validation - Execution Report', header_format)
            
            total_tests = len(df_summary)
            pass_count = len(df_summary[df_summary['Status'] == 'PASS'])
            fail_count = len(df_summary[df_summary['Status'] == 'FAIL'])
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            worksheet_summary.write('A3', 'Execution Date:', stat_header_format)
            worksheet_summary.write('B3', current_time)
            
            worksheet_summary.write('A4', 'Total Verifications:', stat_header_format)
            worksheet_summary.write('B4', total_tests)
            
            worksheet_summary.write('A5', 'System Status:', stat_header_format)
            if fail_count == 0:
                worksheet_summary.write('B5', 'ALL SYSTEMS PASS', pass_format)
            else:
                worksheet_summary.write('B5', f'FAILED ({fail_count} ISSUES)', fail_format)
            
            # --- Write Table Data ---
            start_row = 7
            header_row = start_row
            data_start_row = header_row + 1
            
            if total_tests > 0:
                for row_num in range(total_tests):
                    row_data = df_summary.iloc[row_num]
                    curr_row = data_start_row + row_num
                    
                    worksheet_summary.write(curr_row, 0, row_data['Row_Index'], default_format)
                    worksheet_summary.write(curr_row, 1, row_data['Test_Name'], default_format)
                    
                    status = row_data['Status']
                    if status == 'PASS':
                        worksheet_summary.write(curr_row, 2, status, pass_format)
                    elif status == 'SKIPPED':
                        worksheet_summary.write(curr_row, 2, status, skipped_format)
                    elif status == 'WARNING':
                        worksheet_summary.write(curr_row, 2, status, warning_format)
                    else:
                        worksheet_summary.write(curr_row, 2, status, fail_format)
                    
                    worksheet_summary.write(curr_row, 3, row_data['Expected_Sec'], default_format)
                    worksheet_summary.write(curr_row, 4, row_data['Actual_Sec'], default_format)
                    worksheet_summary.write(curr_row, 5, row_data['Technical_Evidence'], wrap_format)
                
                end_row = data_start_row + total_tests - 1
                worksheet_summary.add_table(header_row, 0, end_row, 5, {
                    'columns': [{'header': c} for c in df_summary.columns.values],
                    'style': 'Table Style Light 9'
                })

            # --- Column Sizing ---
            worksheet_summary.set_column('A:A', 12)
            worksheet_summary.set_column('B:B', 30)
            worksheet_summary.set_column('C:C', 15)
            worksheet_summary.set_column('D:E', 15)
            worksheet_summary.set_column('F:F', 110) # Very wide for evidence with wrapping

            # Auto fit raw telemetry slightly 
            worksheet_raw = writer.sheets['Raw_Telemetry']
            worksheet_raw.set_column('A:A', 12)  # Row_Index
            worksheet_raw.set_column('B:E', 10)  # H, Min, Sec, ms
            worksheet_raw.set_column('F:M', 12)  # Telemetry columns
