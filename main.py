import sys
import datetime
import qtawesome as qta
import pyqtgraph as pg
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QListWidget, QListWidgetItem, QFileDialog, QGroupBox,
                             QCheckBox, QComboBox)
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtCore import Qt, QTimer

from daq_handler import DAQHandler
from logic_monitor import LogicMonitor
from excel_exporter import ExcelExporter

class ColoredAxisItem(pg.AxisItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.channel_meta = {}

    def set_meta(self, meta_dict):
        self.channel_meta = meta_dict

    def drawPicture(self, p, axisSpec, tickSpecs, textSpecs):
        p.setRenderHint(p.Antialiasing, False)
        p.setRenderHint(p.TextAntialiasing, True)

        axis_pen, p1, p2 = axisSpec
        p.setPen(axis_pen)
        p.drawLine(p1, p2)

        for pen, p1, p2 in tickSpecs:
            p.setPen(pen)
            p.drawLine(p1, p2)

        if self.style['tickFont'] is not None:
            p.setFont(self.style['tickFont'])

        for rect, flags, text in textSpecs:
            meta = self.channel_meta.get(text)
            if meta:
                color = meta['color']
                icon_px = meta['icon']
                
                # Draw the icon to the left of the text box
                icon_x = int(rect.x() - 22)
                icon_y = int(rect.y() + (rect.height() - 16) / 2)
                p.drawPixmap(icon_x, icon_y, 16, 16, icon_px)
                
                p.setPen(pg.mkPen(color=color))
            else:
                p.setPen(self.textPen())
                
            p.drawText(rect, flags, text)

class StatusCard(QWidget):
    def __init__(self, title, icon_name):
        super().__init__()
        self.icon_name = icon_name
        layout = QVBoxLayout()
        self.icon_label = QLabel()
        self.icon_label.setPixmap(qta.icon(self.icon_name, color='#E0E0E0').pixmap(40, 40))
        self.icon_label.setAlignment(Qt.AlignCenter)
        
        self.title_label = QLabel(title)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #00BFFF;")
        
        self.val_label = QLabel("0.00 V")
        self.val_label.setAlignment(Qt.AlignCenter)
        self.val_label.setStyleSheet("font-family: Consolas, monospace; font-size: 18px; color: #777777; font-weight: bold;")

        layout.addWidget(self.icon_label)
        layout.addWidget(self.title_label)
        layout.addWidget(self.val_label)
        self.setLayout(layout)
        
        self.setStyleSheet("""
            StatusCard { 
                border: 2px solid #222222; 
                border-radius: 8px; 
                padding: 10px; 
                background-color: #121212; 
            }
        """)

    def update_val(self, val):
        self.val_label.setText(f"{val:.2f} V")
        if val > 3.0:
            self.setStyleSheet("""
                StatusCard { 
                    border: 2px solid #39FF14; 
                    border-radius: 8px; 
                    padding: 10px; 
                    background-color: #0b1f09; 
                }
            """)
            self.val_label.setStyleSheet("font-family: Consolas, monospace; font-size: 18px; color: #39FF14; font-weight: bold;")
            self.icon_label.setPixmap(qta.icon(self.icon_name, color='#39FF14').pixmap(40, 40))
        else:
            self.setStyleSheet("""
                StatusCard { 
                    border: 2px solid #222222; 
                    border-radius: 8px; 
                    padding: 10px; 
                    background-color: #121212; 
                }
            """)
            self.val_label.setStyleSheet("font-family: Consolas, monospace; font-size: 18px; color: #777777; font-weight: bold;")
            self.icon_label.setPixmap(qta.icon(self.icon_name, color='#E0E0E0').pixmap(40, 40))

class MainUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sharp VE BLDC Industrial DAQ Console")
        self.resize(1400, 950)

        self.setStyleSheet("""
            QMainWindow {
                background-color: #0d0d0d;
                color: #ffffff;
            }
            QGroupBox {
                border: 1px solid #333333;
                border-radius: 6px;
                margin-top: 15px;
                font-weight: bold;
                color: #00BFFF;
                font-size: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 5px 0 5px;
            }
            QLabel {
                color: #E0E0E0;
            }
            QPushButton {
                background-color: #1a1a1a;
                border: 1px solid #444444;
                color: #E0E0E0;
                border-radius: 6px;
                padding: 8px;
            }
            QPushButton:hover {
                background-color: #2a2a2a;
                border: 1px solid #00BFFF;
            }
            QPushButton:disabled {
                background-color: #0a0a0a;
                border: 1px solid #222222;
                color: #444444;
            }
            QComboBox, QCheckBox {
                color: #ffffff;
            }
            QComboBox {
                background-color: #1a1a1a;
                border: 1px solid #444444;
                border-radius: 4px;
                padding: 5px;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1a1a;
                color: #ffffff;
                selection-background-color: #00BFFF;
                selection-color: #000000;
                outline: 0px;
            }
            QComboBox::drop-down {
                border: 0px;
            }
            QListWidget {
                background-color: #050505;
                border: 1px solid #333333;
                border-radius: 5px;
                color: #E0E0E0;
                padding: 5px;
            }
        """)

        self.channels = ["Cold_V", "Hot_V", "Pump", "Clutch", "Motor_CW", "Motor_CCW", "Door", "Buzzer"]
        self.icons = ["fa5s.snowflake", "fa5s.fire", "fa5s.tint", "fa5s.cogs", "fa5s.redo", "fa5s.undo", "fa5s.door-closed", "fa5s.bell"]
        
        self.raw_data_log = []
        self.is_recording = False
        self.test_start_time = None
        self.elapsed_timer = QTimer()
        self.elapsed_timer.timeout.connect(self.update_timer_display)
        
        self.setup_ui()
        
        self.daq = DAQHandler(simulate=True)
        self.logic_mon = LogicMonitor()
        
        self.daq.data_ready.connect(self.on_data_ready)
        self.daq.error_occurred.connect(self.on_daq_error)
        self.logic_mon.log_event.connect(self.add_log)
        self.logic_mon.phase_changed.connect(self.update_phase_display)
        
    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        
        header = QLabel("SHARP VE BLDC Automated HIL DAQ System")
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff; letter-spacing: 2px; padding: 10px; background-color: #111111; border: 1px solid #333333;")
        
        top_bar_layout = QHBoxLayout()
        self.phase_label = QLabel("PHASE: IDLE")
        self.phase_label.setAlignment(Qt.AlignCenter)
        self.phase_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #A0A0A0; background-color: #1a1a1a; border: 1px solid #444444; border-radius: 4px; padding: 8px;")
        
        self.time_label = QLabel("⏱️ 00:00:00")
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #00FFFF; background-color: #1a1a1a; border: 1px solid #444444; border-radius: 4px; padding: 8px;")
        
        top_bar_layout.addWidget(header, stretch=3)
        top_bar_layout.addWidget(self.phase_label, stretch=1)
        top_bar_layout.addWidget(self.time_label, stretch=1)
        main_layout.addLayout(top_bar_layout)
        
        legend_layout = QHBoxLayout()
        legend_items = [
            ("IDLE", "#9E9E9E"), ("WEIGHT DETECT", "#FFB74D"), ("WATER FILL", "#4FC3F7"), 
            ("WASH", "#81C784"), ("DRAIN", "#E57373"), ("SPIN", "#9575CD")
        ]
        for text, color in legend_items:
            lbl = QLabel(f"● {text}")
            lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 12px; padding-bottom: 5px;")
            lbl.setAlignment(Qt.AlignCenter)
            legend_layout.addWidget(lbl)
        main_layout.addLayout(legend_layout)
        
        cards_group = QGroupBox("DIGITAL I/O STATUS")
        cards_layout = QHBoxLayout()
        self.cards = []
        for name, icon in zip(self.channels, self.icons):
            card = StatusCard(name, icon)
            self.cards.append(card)
            cards_layout.addWidget(card)
        cards_group.setLayout(cards_layout)
        main_layout.addWidget(cards_group, stretch=1)
        
        graph_group = QGroupBox("LIVE TELEMETRY (OSCILLOSCOPE)")
        graph_layout = QVBoxLayout()
        pg.setConfigOption('background', '#030303') 
        pg.setConfigOption('foreground', '#E0E0E0')
        pg.setConfigOptions(antialias=True) 
        
        # Inject our Custom Left Axis
        custom_axis = ColoredAxisItem(orientation='left')
        custom_axis.setWidth(100) # Give it explicit width so icons aren't cut off
        self.plot_widget = pg.PlotWidget(axisItems={'left': custom_axis})
        
        # Industrial soft color palette replacing harsh neon
        industrial_colors = ['#4DD0E1', '#E57373', '#81C784', '#A1887F', '#FFF176', '#FFB74D', '#64B5F6', '#E0E0E0']
        
        # Meta dictionary to inject into custom axis
        axis_meta = {}
        for i, name in enumerate(self.channels):
            px = qta.icon(self.icons[i], color=industrial_colors[i]).pixmap(16, 16)
            axis_meta[name] = {'color': industrial_colors[i], 'icon': px}
        custom_axis.set_meta(axis_meta)

        y_axis = self.plot_widget.getAxis('left')
        # Anchor the text EXACTLY at the 0V resting line of each axis so they align identically
        ticks = [[(i * 10, name) for i, name in enumerate(self.channels)]]
        y_axis.setTicks(ticks)
        y_axis.setStyle(tickFont=QFont("Consolas", 10, QFont.Bold))
        
        self.plot_widget.showGrid(x=True, y=True, alpha=0.4)
        # Lock vertical range to strictly keep lines at correct offset pixels without drifting
        self.plot_widget.setYRange(0, 80, padding=0.05)
        self.plot_widget.setMouseEnabled(y=False) 
        
        self.curves = []
        for i, name in enumerate(self.channels):
            curve = self.plot_widget.plot(pen=pg.mkPen(color=industrial_colors[i], width=2.5), name=name)
            self.curves.append(curve)
            
        self.plot_widget.addLegend(offset=(10, 10))
        
        graph_layout.addWidget(self.plot_widget)
        graph_group.setLayout(graph_layout)
        main_layout.addWidget(graph_group, stretch=4)
        
        self.time_data = []
        self.y_data = [[] for _ in range(8)]
        
        bottom_layout = QHBoxLayout()
        
        log_group = QGroupBox("SYSTEM TERMINAL LOG")
        log_layout = QVBoxLayout()
        self.log_list = QListWidget()
        self.log_list.setFont(QFont("Consolas", 11))
        log_layout.addWidget(self.log_list)
        log_group.setLayout(log_layout)
        bottom_layout.addWidget(log_group, stretch=4)
        
        ctrl_group = QGroupBox("CONTROL PANEL")
        ctrl_layout = QVBoxLayout()
        
        self.daq_checkbox = QCheckBox("Enable NI-Hardware DAQ")
        self.daq_checkbox.setChecked(False)
        self.daq_checkbox.toggled.connect(self.toggle_daq_mode)
        
        self.program_combo = QComboBox()
        self.program_combo.addItems([
            "Cotton (قطن)",
            "Eco (توفير - البرنامج الاقتصادي)",
            "Mix (مختلط)",
            "Quick Wash (غسيل سريع)",
            "Wool (صوف)",
            "Delicate (ملابس ناعمة/حساسة)",
            "Heavy Duty (ثقيل/شديد الاتساخ)",
            "Blanket (لحاف)",
            "Baby Care (عناية بملابس الأطفال)",
            "Sportswear (ملابس رياضية)",
            "Jeans (جينز)",
            "Drum Clean (تنظيف الحلة)",
            "Rinse + Spin (شطف وعصر)",
            "Spin Only (عصر فقط)",
            "Drain (تصريف المياه فقط)"
        ])
        self.program_combo.currentTextChanged.connect(self.change_program)
        
        self.btn_start = QPushButton(qta.icon('fa5s.play', color='#39FF14'), " START TEST SEQUENCE")
        self.btn_start.setMinimumHeight(45)
        self.btn_start.setStyleSheet("font-size: 14px; font-weight: bold; text-align: left; padding-left: 20px;")
        self.btn_start.clicked.connect(self.start_recording)
        
        self.btn_stop = QPushButton(qta.icon('fa5s.stop', color='#FF3131'), " STOP & EXPORT EXCEL")
        self.btn_stop.setMinimumHeight(45)
        self.btn_stop.setStyleSheet("font-size: 14px; font-weight: bold; text-align: left; padding-left: 20px;")
        self.btn_stop.clicked.connect(self.stop_recording)
        self.btn_stop.setEnabled(False)
        
        ctrl_layout.addWidget(QLabel("Test Program Protocol:"))
        ctrl_layout.addWidget(self.program_combo)
        ctrl_layout.addSpacing(15)
        ctrl_layout.addWidget(self.daq_checkbox)
        ctrl_layout.addSpacing(15)
        ctrl_layout.addWidget(self.btn_start)
        ctrl_layout.addWidget(self.btn_stop)
        ctrl_layout.addStretch()
        ctrl_group.setLayout(ctrl_layout)
        bottom_layout.addWidget(ctrl_group, stretch=1)
        
        main_layout.addLayout(bottom_layout, stretch=2)

    def update_phase_display(self, phase):
        colors = {
            'IDLE': '#9E9E9E',
            'WEIGHT_DETECT': '#FFB74D',
            'WATER_FILL': '#4FC3F7',
            'WASH': '#81C784',
            'DRAIN': '#E57373',
            'SPIN': '#9575CD'
        }
        color = colors.get(phase, '#E0E0E0')
        self.phase_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {color}; background-color: #1a1a1a; border: 1px solid #444444; border-radius: 4px; padding: 8px;")
        self.phase_label.setText(f"PHASE: {phase}")

    def update_timer_display(self):
        if self.is_recording and self.test_start_time:
            elapsed = int((datetime.datetime.now() - self.test_start_time).total_seconds())
            hours, remainder = divmod(elapsed, 3600)
            minutes, seconds = divmod(remainder, 60)
            self.time_label.setText(f"⏱️ {hours:02d}:{minutes:02d}:{seconds:02d}")

    def toggle_daq_mode(self, checked):
        if self.is_recording:
             self.add_log("WARNING: Cannot toggle DAQ mode while execution is in progress!")
             self.daq_checkbox.setChecked(not checked) 
             return
        self.daq.simulate = not checked
        mode_str = "Hardware DAQ" if checked else "Simulation"
        self.add_log(f"System switched to {mode_str} Mode.")

    def change_program(self, text):
        self.logic_mon.set_program(text, level=1)

    def on_daq_error(self, err_msg):
        self.add_log(err_msg)
        if "Falling back to Simulation" in err_msg:
            self.daq_checkbox.blockSignals(True)
            self.daq_checkbox.setChecked(False)
            self.daq_checkbox.blockSignals(False)

    def start_recording(self):
        self.is_recording = True
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.raw_data_log.clear()
        self.logic_mon.reset()
        self.test_start_time = datetime.datetime.now()
        self.elapsed_timer.start(1000)
        self.update_phase_display("IDLE")
        
        self.time_data = []
        self.y_data = [[] for _ in range(8)]
        for curve in self.curves:
            curve.setData([], [])
            
        self.add_log("System initialization complete. Recording started...")
        self.daq.start()

    def stop_recording(self):
        self.is_recording = False
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.daq.stop()
        self.elapsed_timer.stop()
        self.add_log("Execution terminated. Waiting for save dialog...")
        
        filename, _ = QFileDialog.getSaveFileName(self, "Save Execution Report", "Sharp_Validation_Report.xlsx", "Excel Files (*.xlsx)")
        if filename:
            exporter = ExcelExporter(filename)
            try:
                exporter.export(self.raw_data_log, self.logic_mon.get_summary())
                self.add_log(f"SUCCESS: Report saved to {filename}")
            except Exception as e:
                self.add_log(f"ERROR: Failed to save Excel file: {e}")
        else:
            self.add_log("Save canceled by Operator.")

    def on_data_ready(self, data):
        row_idx = len(self.raw_data_log) + 1
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        row = [row_idx, timestamp] + data
        if self.is_recording:
            self.raw_data_log.append(row)
            self.logic_mon.process_row(row)
            
        for i, val in enumerate(data):
            self.cards[i].update_val(val)
            
        self.time_data.append(row_idx)
        for i, val in enumerate(data):
            offset_val = val + (i * 10)
            self.y_data[i].append(offset_val)
            
        if len(self.time_data) > 300: 
            self.time_data = self.time_data[-300:]
            for i in range(8):
                self.y_data[i] = self.y_data[i][-300:]
                
        for i, curve in enumerate(self.curves):
            curve.setData(self.time_data, self.y_data[i])

    def add_log(self, text):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        item = QListWidgetItem(f"[{ts}] {text}")
        
        if "SECURITY FAULT" in text or "FAIL" in text or "ERROR" in text or "Error" in text:
            item.setForeground(QColor("#FF3131")) 
        elif "PASS" in text or "SUCCESS" in text or "perfectly" in text:
            item.setForeground(QColor("#39FF14")) 
        elif "WARNING" in text or "Warning" in text:
            item.setForeground(QColor("#FFEA00")) 
        else:
            item.setForeground(QColor("#00BFFF")) 
            
        self.log_list.addItem(item)
        self.log_list.scrollToBottom()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainUI()
    window.show()
    sys.exit(app.exec_())
