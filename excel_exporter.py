import pandas as pd
import xlsxwriter
from datetime import datetime

class ExcelExporter:
    def __init__(self, filename):
        self.filename = filename

    def export(self, raw_data, summary_data):
        columns_raw = [
            "Row_Index", "Timestamp", "Cold_V", "Hot_V", 
            "Pump", "Clutch", "Motor_CW", "Motor_CCW", "Door", "Buzzer"
        ]
        df_raw = pd.DataFrame(raw_data, columns=columns_raw)
        
        columns_summary = ["Row_Index", "Test_Name", "Status", "Technical_Evidence"]
        df_summary = pd.DataFrame(summary_data, columns=columns_summary)

        with pd.ExcelWriter(self.filename, engine='xlsxwriter') as writer:
            df_raw.to_excel(writer, sheet_name="Raw_Telemetry", index=False)
            
            workbook = writer.book
            worksheet_summary = workbook.add_worksheet('Analysis_Summary')
            
            # --- Formats ---
            header_format = workbook.add_format({
                'bold': True, 'font_size': 14, 
                'bg_color': '#1E2A38', 'font_color': 'white', 
                'align': 'center', 'valign': 'vcenter'
            })
            wrap_format = workbook.add_format({'text_wrap': True, 'valign': 'top'})
            pass_format = workbook.add_format({'bg_color': '#C6EFCE', 'font_color': '#006100', 'bold': True})
            fail_format = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006', 'bold': True})
            default_format = workbook.add_format({'valign': 'top'})
            
            # --- Write Header Stats ---
            worksheet_summary.merge_range('A1:D1', 'Sharp HIL DAQ Verification Report', header_format)
            
            total_tests = len(df_summary)
            pass_count = len(df_summary[df_summary['Status'] == 'PASS'])
            fail_count = len(df_summary[df_summary['Status'] == 'FAIL'])
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            worksheet_summary.write('A3', 'Execution Date:', workbook.add_format({'bold': True}))
            worksheet_summary.write('B3', current_time)
            
            worksheet_summary.write('A4', 'Total Verifications:', workbook.add_format({'bold': True}))
            worksheet_summary.write('B4', total_tests)
            
            worksheet_summary.write('A5', 'Passed Checks:', workbook.add_format({'bold': True}))
            worksheet_summary.write('B5', pass_count, pass_format)
            
            worksheet_summary.write('A6', 'Failed Checks:', workbook.add_format({'bold': True}))
            worksheet_summary.write('B6', fail_count, fail_format)
            
            # --- Write Table Data ---
            start_row = 8
            
            if total_tests > 0:
                for row_num in range(total_tests):
                    row_data = df_summary.iloc[row_num]
                    worksheet_summary.write(start_row + 1 + row_num, 0, row_data['Row_Index'], default_format)
                    worksheet_summary.write(start_row + 1 + row_num, 1, row_data['Test_Name'], default_format)
                    
                    status = row_data['Status']
                    if status == 'PASS':
                        worksheet_summary.write(start_row + 1 + row_num, 2, status, pass_format)
                    else:
                        worksheet_summary.write(start_row + 1 + row_num, 2, status, fail_format)
                        
                    worksheet_summary.write(start_row + 1 + row_num, 3, row_data['Technical_Evidence'], wrap_format)
                
                end_row = start_row + total_tests
                worksheet_summary.add_table(f'A{start_row+1}:D{end_row+1}', {
                    'columns': [{'header': c} for c in df_summary.columns.values],
                    'style': 'Table Style Light 9'
                })

            # --- Column Sizing ---
            worksheet_summary.set_column('A:A', 12)
            worksheet_summary.set_column('B:B', 30)
            worksheet_summary.set_column('C:C', 15)
            worksheet_summary.set_column('D:D', 110) # Very wide for evidence with wrapping

            # Auto fit raw telemetry slightly 
            worksheet_raw = writer.sheets['Raw_Telemetry']
            worksheet_raw.set_column('A:A', 12)
            worksheet_raw.set_column('B:B', 25)
            worksheet_raw.set_column('C:J', 12)
