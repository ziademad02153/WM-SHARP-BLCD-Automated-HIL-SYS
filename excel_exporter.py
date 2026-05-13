# SHARP HIL REPORTING MODULE - VERSION 2.1
import pandas as pd
import xlsxwriter
from datetime import datetime

class ExcelExporter:
    def __init__(self, filename):
        self.filename = filename

    def export(self, raw_data, summary_data):
        columns_raw = [
            "Row_Index", "Timestamp", "Motor_RPM", "Cold_V", "Hot_V",
            "Softener", "GearMotor", "Empty", "Pump", "Door"
        ]
        df_raw = pd.DataFrame(raw_data, columns=columns_raw)
        
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
            worksheet_raw.set_column('A:A', 12)
            worksheet_raw.set_column('B:B', 25)
            worksheet_raw.set_column('C:J', 12)
