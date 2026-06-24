# SHARP AUTOMATED SOFTWARE VALIDATION SYSTEM - R&D EDITION
import sys
import os
import datetime
import qtawesome as qta
import pyqtgraph as pg
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QListWidget, QListWidgetItem, QFileDialog, QGroupBox,
                             QCheckBox, QComboBox, QFrame, QMessageBox, QGraphicsOpacityEffect,
                             QGridLayout, QSizePolicy)
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
        
        self.unit = " RPM" if title == "Motor_RPM" else " V"
        
        self.val_label = QLabel(f"0.00{self.unit}")
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
        self.val_label.setText(f"{val:.2f}{self.unit}")
        # Threshold lowered to 2.0V to capture all active signals (Softener, Valves, etc.)
        if val > 2.0:
            self.setStyleSheet("""
                StatusCard { 
                    border: 2px solid #39FF14; 
                    border-radius: 6px; 
                    padding: 10px; 
                    background-color: #0a1c0e; 
                }
            """)
            self.val_label.setStyleSheet("font-family: 'Consolas', monospace; font-size: 19px; color: #39FF14; font-weight: bold;")
            self.icon_label.setPixmap(qta.icon(self.icon_name, color='#39FF14').pixmap(36, 36))
        else:
            self.setStyleSheet("""
                StatusCard { 
                    border: 1px solid #2d3239; 
                    border-radius: 6px; 
                    padding: 10px; 
                    background-color: #111418; 
                }
            """)
            self.val_label.setStyleSheet("font-family: 'Consolas', monospace; font-size: 19px; color: #94a3b8; font-weight: bold;")
            self.icon_label.setPixmap(qta.icon(self.icon_name, color='#455a64').pixmap(36, 36))

class MainUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sharp VE BLDC Industrial DAQ Console")
        self.resize(1400, 950)

        self.setStyleSheet("""
            QMainWindow { background-color: #0d0f12; color: #e0e0e0; }
            QGroupBox {
                border: 1px solid #2d3239; border-radius: 4px; margin-top: 15px;
                font-weight: bold; color: #00D4FF; font-size: 13px; letter-spacing: 1px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QLabel { color: #cfd8dc; font-family: 'Segoe UI', sans-serif; }
            QPushButton {
                background-color: #1a1d21; border: 1px solid #3c444d; color: #e0e0e0;
                border-radius: 4px; padding: 10px; font-weight: bold;
            }
            QPushButton:hover { background-color: #252a30; border: 1px solid #00D4FF; }
            QPushButton:disabled { background-color: #0a0a0a; border: 1px solid #222222; color: #444444; }
            QComboBox { background-color: #1a1d21; border: 1px solid #3c444d; border-radius: 4px; padding: 5px; color: white; }
            QListWidget { background-color: #050608; border: 1px solid #2d3239; color: #00FF41; font-family: 'Consolas', monospace; }
        """)

        self.channels = ["Motor_RPM", "Cold_V", "Hot_V", "Softener", "GearMotor", "Empty", "Pump", "Door"]
        self.icons = ["fa5s.tachometer-alt", "fa5s.snowflake", "fa5s.fire", "fa5s.flask", "fa5s.cog", "fa5s.minus", "fa5s.tint", "fa5s.door-closed"]
        
        self.raw_data_log = []
        self.is_recording = False
        self.test_start_time = None
        self.elapsed_timer = QTimer()
        self.elapsed_timer.timeout.connect(self.update_timer_display)
        
        self.setup_ui()
        
        self.daq = DAQHandler()
        self.logic_mon = LogicMonitor()
        
        self.daq.data_ready.connect(self.on_data_ready)
        self.daq.error_occurred.connect(self.on_daq_error)
        self.logic_mon.log_event.connect(self.add_log)
        self.logic_mon.phase_changed.connect(self.update_phase_display)
        self.logic_mon.validation_status.connect(self.update_validation_display)
        self.logic_mon.error_monitor.alarm_triggered.connect(self.handle_alarm)
        self.logic_mon.spin_logic_status.connect(self.update_spin_status)
        self.logic_mon.pump_duty_status.connect(self.update_pump_status)
        
    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        header_container = QFrame()
        header_container.setStyleSheet("background-color: #14171c; border-bottom: 2px solid #00D4FF; border-radius: 0px;")
        header_layout = QHBoxLayout(header_container)
        
        title_vbox = QVBoxLayout()
        header_text = QLabel("SHARP AUTOMATED SOFTWARE VALIDATION CONSOLE")
        header_text.setStyleSheet("font-size: 20px; font-weight: bold; color: #ffffff; letter-spacing: 1px; border: none;")
        sub_text = QLabel("PRECISION BLDC HIL TESTING SYSTEM | EL ARABY GROUP")
        sub_text.setStyleSheet("font-size: 10px; font-weight: bold; color: #00D4FF; letter-spacing: 2px; border: none;")
        title_vbox.addWidget(header_text)
        title_vbox.addWidget(sub_text)
        
        self.phase_label = QLabel("PHASE: IDLE")
        self.phase_label.setAlignment(Qt.AlignCenter)
        self.phase_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #A0A0A0; background-color: #0a0c0f; border: 1px solid #2d3239; border-radius: 4px; padding: 10px; min-width: 150px;")
        
        self.time_label = QLabel("00:00:00")
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #00D4FF; background-color: #0a0c0f; border: 1px solid #2d3239; border-radius: 4px; padding: 10px; min-width: 150px; font-family: 'Consolas';")
        
        header_layout.addLayout(title_vbox, stretch=3)
        header_layout.addStretch()
        header_layout.addWidget(self.phase_label, stretch=1)
        header_layout.addWidget(self.time_label, stretch=1)
        main_layout.addWidget(header_container)
        
        legend_layout = QHBoxLayout()
        legend_items = [
            ("IDLE", "#9E9E9E"), ("WEIGHT_DETECT", "#FFB74D"), ("WATER_FILL", "#4FC3F7"), 
            ("WASH", "#81C784"), ("RINSE", "#F06292"), ("DRAIN", "#E57373"), ("SPIN", "#9575CD")
        ]
        self.phase_blocks = {}
        for text, color in legend_items:
            lbl = QLabel(f"BLOCK: {text}")
            lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 11px; padding-bottom: 5px; opacity: 0.5;")
            lbl.setGraphicsEffect(QGraphicsOpacityEffect()) # Prep for highlighting
            lbl.graphicsEffect().setOpacity(0.3)
            lbl.setAlignment(Qt.AlignCenter)
            legend_layout.addWidget(lbl)
            self.phase_blocks[text] = (lbl, color)
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

        val_group = QGroupBox("SEQUENCE VALIDATION STATUS")
        val_layout = QHBoxLayout()
        self.expected_phase_label = QLabel("EXPECTED: ---")
        self.expected_phase_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #4FC3F7; background-color: #111111; padding: 5px; border-radius: 3px;")
        self.countdown_label = QLabel("TIME: --:--")
        self.countdown_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #FFEB3B; background-color: #111111; padding: 5px; border-radius: 3px;")
        self.seq_status_label = QLabel("STATUS: IDLE")
        self.seq_status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #9E9E9E; background-color: #111111; padding: 5px; border-radius: 3px;")
        val_layout.addWidget(self.expected_phase_label, stretch=2)
        val_layout.addWidget(self.countdown_label, stretch=1)
        val_layout.addWidget(self.seq_status_label, stretch=1)
        val_group.setLayout(val_layout)
        main_layout.addWidget(val_group)
        
        graph_group = QGroupBox("LIVE TELEMETRY (OSCILLOSCOPE)")
        graph_layout = QVBoxLayout()
        pg.setConfigOption('background', '#030303') 
        pg.setConfigOption('foreground', '#E0E0E0')
        pg.setConfigOptions(antialias=True) 
        custom_axis = ColoredAxisItem(orientation='left')
        custom_axis.setWidth(100)
        self.plot_widget = pg.PlotWidget(axisItems={'left': custom_axis})
        industrial_colors = ['#4DD0E1', '#E57373', '#81C784', '#A1887F', '#FFF176', '#FFB74D', '#64B5F6', '#E0E0E0']
        axis_meta = {}
        for i, name in enumerate(self.channels):
            px = qta.icon(self.icons[i], color=industrial_colors[i]).pixmap(16, 16)
            axis_meta[name] = {'color': industrial_colors[i], 'icon': px}
        custom_axis.set_meta(axis_meta)
        y_axis = self.plot_widget.getAxis('left')
        ticks = [[(i * 10, name) for i, name in enumerate(self.channels)]]
        y_axis.setTicks(ticks)
        y_axis.setStyle(tickFont=QFont("Consolas", 10, QFont.Bold))
        self.plot_widget.showGrid(x=True, y=True, alpha=0.4)
        self.plot_widget.setYRange(0, 80, 0.05)
        self.plot_widget.setMouseEnabled(y=False) 
        self.curves = []
        for i, name in enumerate(self.channels):
            curve = self.plot_widget.plot(pen=pg.mkPen(color=industrial_colors[i], width=2.5), name=name)
            self.curves.append(curve)
        self.plot_widget.addLegend(offset=(10, 10))
        graph_layout.addWidget(self.plot_widget)
        graph_group.setLayout(graph_layout)
        main_layout.addWidget(graph_group, stretch=4)
        
        bottom_layout = QHBoxLayout()
        log_group = QGroupBox("SYSTEM TERMINAL LOG")
        log_layout = QVBoxLayout()
        self.log_list = QListWidget()
        self.log_list.setFont(QFont("Consolas", 11))
        log_layout.addWidget(self.log_list)
        log_group.setLayout(log_layout)
        bottom_layout.addWidget(log_group, stretch=4)
        
        ctrl_group = QGroupBox("CONTROL PANEL")
        ctrl_layout = QHBoxLayout()
        left_vbox = QVBoxLayout()
        right_vbox = QVBoxLayout()

        self.program_combo = QComboBox()
        self.program_combo.addItems(["Regular", "Quick", "Heavy", "Baby Care", "Cotton", "Delicates", "Wool", "Jeans", "Blanket", "Quick Rinse", "Sports Wear", "Tub Clean"])
        self.program_combo.currentTextChanged.connect(self.change_program)
        
        self.btn_start = QPushButton(qta.icon('fa5s.play', color='#39FF14'), " START TEST SEQUENCE")
        self.btn_start.setMinimumHeight(45)
        self.btn_start.clicked.connect(self.start_recording)
        
        self.btn_stop = QPushButton(qta.icon('fa5s.stop', color='#FF3131'), " STOP TEST")
        self.btn_stop.setMinimumHeight(45)
        self.btn_stop.clicked.connect(self.stop_recording)
        self.btn_stop.setEnabled(False)
        
        self.btn_force_save = QPushButton(qta.icon('fa5s.save', color='#00D4FF'), " EXPORT TO EXCEL")
        self.btn_force_save.setMinimumHeight(45)
        self.btn_force_save.clicked.connect(self.save_report)
        
        self.level_combo = QComboBox()
        self.level_combo.addItems(["LEV-1", "LEV-2", "LEV-3", "LEV-4"])
        self.level_combo.currentTextChanged.connect(lambda: self.change_program(self.program_combo.currentText()))
        
        self.soak_combo = QComboBox()
        self.soak_combo.addItems(["No Soak", "1 Hour", "2 Hours", "4 Hours"])
        self.soak_combo.currentTextChanged.connect(lambda: self.change_program(self.program_combo.currentText()))
        
        self.delay_combo = QComboBox()
        delay_options = ["None"] + [f"{i} Hour{'s' if i > 1 else ''}" for i in range(1, 25)]
        self.delay_combo.addItems(delay_options)
        self.delay_combo.currentTextChanged.connect(lambda: self.change_program(self.program_combo.currentText()))

        # Custom time overrides (reference for agitation validator)
        self.wash_time_combo = QComboBox()
        wash_opts = ["Default"] + [f"{m} Min" for m in [5,8,10,12,15,18,20,25,30,35,40,45,50,55,60]]
        self.wash_time_combo.addItems(wash_opts)

        self.rinse_time_combo = QComboBox()
        rinse_opts = ["Default"] + [f"{m} Min" for m in [2,3,4,5,6,7,8,10,12,15]]
        self.rinse_time_combo.addItems(rinse_opts)

        self.spin_time_combo = QComboBox()
        spin_opts = ["Default"] + [f"{m} Min" for m in [3,5,6,7,8,9,10,12,15]]
        self.spin_time_combo.addItems(spin_opts)

        # Populate Left Layout
        left_vbox.addWidget(QLabel("Test Program Protocol:"))
        left_vbox.addWidget(self.program_combo)
        left_vbox.addSpacing(5)
        left_vbox.addWidget(QLabel("Target Water Level:"))
        left_vbox.addWidget(self.level_combo)
        left_vbox.addSpacing(5)
        left_vbox.addWidget(QLabel("Soak Time Option:"))
        left_vbox.addWidget(self.soak_combo)
        left_vbox.addSpacing(5)
        left_vbox.addWidget(QLabel("Delay Start:"))
        left_vbox.addWidget(self.delay_combo)
        left_vbox.addSpacing(15)
        left_vbox.addWidget(self.btn_start)
        left_vbox.addWidget(self.btn_stop)
        left_vbox.addWidget(self.btn_force_save)
        left_vbox.addStretch()

        # Populate Right Layout
        lbl_style = "color: #00D4FF; font-weight: bold; font-size: 11px;"
        lbl_w = QLabel("Wash Time Override:")
        lbl_w.setStyleSheet(lbl_style)
        right_vbox.addWidget(lbl_w)
        right_vbox.addWidget(self.wash_time_combo)
        right_vbox.addSpacing(15)
        
        lbl_r = QLabel("Rinse Time Override:")
        lbl_r.setStyleSheet(lbl_style)
        right_vbox.addWidget(lbl_r)
        right_vbox.addWidget(self.rinse_time_combo)
        right_vbox.addSpacing(15)
        
        lbl_s = QLabel("Spin Time Override:")
        lbl_s.setStyleSheet(lbl_style)
        right_vbox.addWidget(lbl_s)
        right_vbox.addWidget(self.spin_time_combo)
        right_vbox.addStretch()

        # Add to main ctrl layout
        ctrl_layout.addLayout(left_vbox, stretch=1)
        ctrl_layout.addSpacing(10)
        ctrl_layout.addLayout(right_vbox, stretch=1)
        ctrl_group.setLayout(ctrl_layout)
        
        adv_group = QGroupBox("ADVANCED LOGIC MONITORING")
        adv_layout = QVBoxLayout()
        self.spin_logic_indicator = QLabel("SPIN DYNAMICS: IDLE")
        self.spin_logic_indicator.setStyleSheet("color: #9E9E9E; font-weight: bold; font-size: 13px; padding: 5px;")
        self.pump_duty_indicator = QLabel("PUMP DUTY CYCLE: OK")
        self.pump_duty_indicator.setStyleSheet("color: #39FF14; font-weight: bold; font-size: 13px; padding: 5px;")
        adv_layout.addWidget(self.spin_logic_indicator)
        adv_layout.addWidget(self.pump_duty_indicator)
        adv_group.setLayout(adv_layout)
        
        bottom_layout.addWidget(adv_group, stretch=1)
        bottom_layout.addWidget(ctrl_group, stretch=1)
        main_layout.addLayout(bottom_layout, stretch=2)

    def update_phase_display(self, phase):
        colors = {
            'IDLE': '#9E9E9E', 'WEIGHT_DETECT': '#FFD700', 'WATER_FILL': '#00BFFF', 
            'WASH': '#32CD32', 'RINSE': '#F06292', 'DRAIN': '#FF4500', 
            'SPIN_PAUSE': '#FF00FF', 'SPIN': '#8A2BE2'
        }
        
        # Handle sub-phases like RINSE_1, RINSE_2
        display_phase = phase
        logic_phase = phase
        if phase.startswith('RINSE'): logic_phase = 'RINSE'
        if phase == 'SPIN_PAUSE': logic_phase = 'SPIN'
        
        color = colors.get(logic_phase, '#20B2AA')
        self.phase_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {color}; background-color: #1a1a1a; border: 1px solid #444444; border-radius: 4px; padding: 8px;")
        self.phase_label.setText(f"PHASE: {display_phase}")
        
        # Highlight active block
        for name, (lbl, orig_color) in self.phase_blocks.items():
            if name == logic_phase:
                lbl.setStyleSheet(f"color: {orig_color}; font-weight: bold; font-size: 13px; border-bottom: 2px solid {orig_color};")
                lbl.graphicsEffect().setOpacity(1.0)
            else:
                lbl.setStyleSheet(f"color: {orig_color}; font-weight: bold; font-size: 11px; border: none;")
                lbl.graphicsEffect().setOpacity(0.2)

    def update_validation_display(self, status_dict):
        exp = status_dict.get("expected_phase", "---")
        time_left = status_dict.get("time_left", 0)
        status = status_dict.get("status", "IDLE")
        mins, secs = divmod(int(time_left), 60)
        self.expected_phase_label.setText(f"EXPECTED: {exp}")
        self.countdown_label.setText(f"TIME: {mins:02d}:{secs:02d}")
        self.seq_status_label.setText(f"STATUS: {status}")
        color = "#FF5252" if status == "FAIL" else "#4CAF50" if status == "RUNNING" else "#9E9E9E"
        self.seq_status_label.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {color}; background-color: #111111; padding: 5px; border-radius: 3px;")

    def update_spin_status(self, text, color):
        self.spin_logic_indicator.setText(f"SPIN DYNAMICS: {text}")
        self.spin_logic_indicator.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 13px; padding: 5px;")

    def update_pump_status(self, text, color):
        self.pump_duty_indicator.setText(f"PUMP DUTY CYCLE: {text}")
        self.pump_duty_indicator.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 13px; padding: 5px;")

    def update_timer_display(self):
        if self.is_recording and self.test_start_time:
            elapsed = int((datetime.datetime.now() - self.test_start_time).total_seconds())
            hours, rem = divmod(elapsed, 3600)
            mins, secs = divmod(rem, 60)
            self.time_label.setText(f"{hours:02d}:{mins:02d}:{secs:02d}")

    def change_program(self, text):
        level_str = self.level_combo.currentText()
        soak_str = self.soak_combo.currentText()
        delay_str = self.delay_combo.currentText()
        self.logic_mon.set_program(text, level=level_str, soak_option=soak_str, delay_option=delay_str) 

    def on_daq_error(self, err_msg):
        self.add_log(f"DAQ ERROR: {err_msg}")
        if self.is_recording:
            self.stop_recording()

    def start_recording(self):
        self.is_recording = True
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.raw_data_log.clear()
        self.logic_mon.reset()
        self.test_start_time = datetime.datetime.now()
        self.elapsed_timer.start(1000)
        self.time_data = []
        self.y_data = [[] for _ in range(8)]
        for curve in self.curves: curve.setData([], [])
        self.add_log("System started...")
        self.change_program(self.program_combo.currentText())
        self.daq.start()

    def stop_recording(self, triggered_by_ui=True):
        if self.is_recording:
            self.is_recording = False
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.daq.stop()
            self.elapsed_timer.stop()
            self.add_log("Recording stopped. Use BLUE BUTTON to save if needed.")
            
    def save_report(self):
        if len(self.raw_data_log) > 0:
            try:
                ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                
                # Generate descriptive filename matching auto_save
                prog_name = self.program_combo.currentText().replace(" ", "")
                lev_name = self.level_combo.currentText()
                load_map = {"LEV-1": "2k", "LEV-2": "4k", "LEV-3": "6k", "LEV-4": "13k"}
                load_str = load_map.get(lev_name, lev_name)
                
                wash_over = self.wash_time_combo.currentText()
                rinse_over = self.rinse_time_combo.currentText()
                spin_over = self.spin_time_combo.currentText()
                is_default = (wash_over == "Default" and rinse_over == "Default" and spin_over == "Default")
                settings_str = "Default" if is_default else "Custom"
                
                suggested_name = f"{prog_name}_{lev_name}_{load_str}_{settings_str}_{ts}.xlsx"
                
                self.add_log("Opening save dialog...")
                file_path, _ = QFileDialog.getSaveFileName(
                    self, "Save Test Report", 
                    suggested_name,
                    "Excel Files (*.xlsx)"
                )
                
                if file_path:
                    summary = self.logic_mon.get_summary()
                    test_cases = summary['test_cases'].copy() if isinstance(summary, dict) and 'test_cases' in summary else list(summary)
                    
                    # Run automated agitation timings analysis (M1 to MU)
                    agitation_defects = []
                    try:
                        import agitation_analyzer
                        self.add_log("Running automated motor agitation timing validator...")
                        agitation_defects = agitation_analyzer.analyze_telemetry(
                            self.raw_data_log,
                            self.program_combo.currentText(),
                            self.level_combo.currentText(),
                            wash_override=self.wash_time_combo.currentText(),
                            rinse_override=self.rinse_time_combo.currentText(),
                            spin_override=self.spin_time_combo.currentText()
                        )
                        self.add_log(f"Agitation validation: {len(agitation_defects)} defects found.", "SUCCESS")
                    except Exception as ag_err:
                        self.add_log(f"AGITATION VALIDATOR ERROR: {ag_err}", "ERROR")

                    exporter = ExcelExporter(file_path)
                    exporter.export(self.raw_data_log, test_cases, defect_data=agitation_defects)
                    self.add_log("REPORT SAVED SUCCESSFULLY", "SUCCESS")
                    QMessageBox.information(self, "Save Success", f"Report saved successfully.")
                else:
                    self.add_log("Save cancelled.")
            except Exception as e:
                self.add_log(f"SAVE ERROR: {e}", "ERROR")
                QMessageBox.critical(self, "Save Error", f"Could not save file: {e}")
        else:
            QMessageBox.warning(self, "No Data", "There is no recorded data to save yet.")

    def auto_save_report(self):
        import os
        save_dir = r"C:\WM-REC"
        if not os.path.exists(save_dir): os.makedirs(save_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        
        summary = self.logic_mon.get_summary()
        test_cases = summary['test_cases'].copy() if isinstance(summary, dict) and 'test_cases' in summary else list(summary)
        
        # Run automated agitation timings analysis (M1 to MU)
        agitation_defects = []
        try:
            import agitation_analyzer
            self.add_log("Running automated motor agitation timing validator...")
            agitation_defects = agitation_analyzer.analyze_telemetry(
                self.raw_data_log,
                self.program_combo.currentText(),
                self.level_combo.currentText(),
                wash_override=self.wash_time_combo.currentText(),
                rinse_override=self.rinse_time_combo.currentText(),
                spin_override=self.spin_time_combo.currentText()
            )
            self.add_log(f"Agitation validation: {len(agitation_defects)} defects found.", "SUCCESS")
        except Exception as ag_err:
            self.add_log(f"AGITATION VALIDATOR ERROR: {ag_err}", "ERROR")

        # Determine final status
        final_status = "SUCCESS"
        for entry in test_cases:
            if entry["Status"] == "FAIL":
                final_status = "FAULT"
                break
        if agitation_defects:
            final_status = "FAULT"

        # Generate descriptive filename
        prog_name = self.program_combo.currentText().replace(" ", "")
        lev_name = self.level_combo.currentText()
        
        # Map levels to approximate loads based on Sharp standards
        load_map = {"LEV-1": "2k", "LEV-2": "4k", "LEV-3": "6k", "LEV-4": "13k"}
        load_str = load_map.get(lev_name, lev_name)
        
        wash_over = self.wash_time_combo.currentText()
        rinse_over = self.rinse_time_combo.currentText()
        spin_over = self.spin_time_combo.currentText()
        
        is_default = (wash_over == "Default" and rinse_over == "Default" and spin_over == "Default")
        settings_str = "Default" if is_default else "Custom"

        file_prefix = f"{prog_name}_{lev_name}_{load_str}_{settings_str}_{final_status}_{ts}"
        filename = os.path.join(save_dir, f"{file_prefix}.xlsx")
        exporter = ExcelExporter(filename)
        try:
            exporter.export(self.raw_data_log, test_cases, defect_data=agitation_defects)
            self.add_log(f"REPORT SAVED: {filename}")
        except Exception as e:
            self.add_log(f"SAVE ERROR: {e}")

    def on_data_ready(self, data):
        data = list(data)
        row_idx = len(self.raw_data_log) + 1
        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        row = [row_idx, timestamp] + data
        if self.is_recording:
            self.raw_data_log.append(row)
            self.logic_mon.process_row(row)
        for i, val in enumerate(data): self.cards[i].update_val(val)
        self.time_data.append(row_idx)
        for i, val in enumerate(data):
            plot_val = val / 100.0 if i == 0 else val
            self.y_data[i].append(plot_val + (i * 10))
        if len(self.time_data) > 1000:
            self.time_data = self.time_data[-1000:]
            for i in range(8): self.y_data[i] = self.y_data[i][-1000:]
        for i, curve in enumerate(self.curves): curve.setData(self.time_data, self.y_data[i])

    def add_log(self, text, level="INFO"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        item = QListWidgetItem(f"[{ts}] {text}")
        if level == "ERROR" or any(x in text for x in ["ERROR", "FAIL", "Fault"]): 
            item.setForeground(QColor("#FF3131"))
        elif level == "SUCCESS" or any(x in text for x in ["OK", "SUCCESS", "PASS"]): 
            item.setForeground(QColor("#39FF14"))
        elif level == "WARNING" or "WARNING" in text: 
            item.setForeground(QColor("#FFEA00"))
        else: 
            item.setForeground(QColor("#00BFFF"))
        self.log_list.addItem(item)
        self.log_list.scrollToBottom()
        if self.log_list.count() > 500: self.log_list.takeItem(0)

    def handle_alarm(self, message):
        # Auto-stop disabled per user request to ensure continuous recording
        # if self.is_recording: self.stop_recording(auto_save=True) 
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setWindowTitle("CRITICAL SYSTEM FAULT")
        msg_box.setText(message)
        msg_box.setStyleSheet("QMessageBox { background-color: #1a0000; color: white; } QLabel { color: #ff6666; }")
        msg_box.exec_()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainUI()
    window.show()
    sys.exit(app.exec_())
