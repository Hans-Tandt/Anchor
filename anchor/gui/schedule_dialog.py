"""Dialog to create/update a Windows scheduled task for a profile."""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from ..core.profile import BackupProfile, save_profile
from .. import scheduler


DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


class ScheduleDialog(QtWidgets.QDialog):
    def __init__(self, parent, profile: BackupProfile):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle(f"Schedule — {profile.name}")
        self.setMinimumWidth(440)

        layout = QtWidgets.QFormLayout(self)
        layout.setContentsMargins(18, 18, 18, 18); layout.setSpacing(10)

        self.enable_chk = QtWidgets.QCheckBox("Run this backup on a schedule")
        self.enable_chk.setChecked(profile.schedule_enabled)
        layout.addRow(self.enable_chk)

        self.freq = QtWidgets.QComboBox()
        self.freq.addItems(["Daily", "Weekly", "At sign-in"])
        layout.addRow("Frequency:", self.freq)

        self.time = QtWidgets.QTimeEdit()
        self.time.setDisplayFormat("HH:mm")
        self.time.setTime(QtCore.QTime(3, 0))
        layout.addRow("Start time:", self.time)

        self.days_box = QtWidgets.QWidget()
        dl = QtWidgets.QHBoxLayout(self.days_box); dl.setContentsMargins(0, 0, 0, 0)
        self.day_checks = {}
        for d in DAYS:
            cb = QtWidgets.QCheckBox(d)
            self.day_checks[d] = cb
            dl.addWidget(cb)
        dl.addStretch(1)
        self.day_checks["MON"].setChecked(True)
        layout.addRow("Days (weekly):", self.days_box)

        # Pre-fill from profile.schedule_cron if it looks parseable
        if profile.schedule_cron:
            self._parse_human(profile.schedule_cron)
        self.freq.currentIndexChanged.connect(self._refresh)
        self._refresh()

        # Buttons
        btns = QtWidgets.QHBoxLayout()
        remove_btn = QtWidgets.QPushButton("Remove schedule")
        remove_btn.setObjectName("danger")
        remove_btn.clicked.connect(self._remove)
        btns.addWidget(remove_btn)
        btns.addStretch(1)
        cancel = QtWidgets.QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        ok = QtWidgets.QPushButton("Save"); ok.setObjectName("primary"); ok.clicked.connect(self._accept)
        btns.addWidget(cancel); btns.addWidget(ok)
        layout.addRow(btns)

    def _refresh(self) -> None:
        freq = self.freq.currentIndex()
        self.time.setEnabled(freq in (0, 1))
        self.days_box.setEnabled(freq == 1)

    def _parse_human(self, s: str) -> None:
        if "logon" in s.lower() or "sign in" in s.lower():
            self.freq.setCurrentIndex(2)
        elif "week" in s.lower() or any(d in s.upper() for d in DAYS):
            self.freq.setCurrentIndex(1)
            for d in DAYS:
                if d in s.upper():
                    self.day_checks[d].setChecked(True)
        else:
            self.freq.setCurrentIndex(0)
        # crude HH:MM extraction
        for tok in s.split():
            if ":" in tok and len(tok) <= 5:
                try:
                    h, m = tok.split(":")
                    self.time.setTime(QtCore.QTime(int(h), int(m)))
                except Exception:
                    pass

    def _build_spec(self) -> scheduler.ScheduleSpec:
        idx = self.freq.currentIndex()
        if idx == 2:
            return scheduler.ScheduleSpec(frequency="ONLOGON", start_time="")
        st = self.time.time().toString("HH:mm")
        if idx == 1:
            chosen = [d for d, cb in self.day_checks.items() if cb.isChecked()]
            return scheduler.ScheduleSpec(
                frequency="WEEKLY", start_time=st,
                days=",".join(chosen) or "MON",
            )
        return scheduler.ScheduleSpec(frequency="DAILY", start_time=st)

    def _remove(self) -> None:
        err = scheduler.delete(self.profile.id)
        if err:
            QtWidgets.QMessageBox.warning(self, "Couldn't remove schedule", err)
            return
        self.profile.schedule_enabled = False
        self.profile.schedule_cron = ""
        save_profile(self.profile)
        QtWidgets.QMessageBox.information(self, "Removed", "Scheduled task removed.")
        self.accept()

    def _accept(self) -> None:
        if not self.enable_chk.isChecked():
            err = scheduler.delete(self.profile.id)
            self.profile.schedule_enabled = False
            self.profile.schedule_cron = ""
            save_profile(self.profile)
            self.accept(); return
        spec = self._build_spec()
        err = scheduler.create_or_update(self.profile.id, spec)
        if err:
            QtWidgets.QMessageBox.warning(self, "Schedule failed", err)
            return
        self.profile.schedule_enabled = True
        self.profile.schedule_cron = spec.human()
        save_profile(self.profile)
        QtWidgets.QMessageBox.information(
            self, "Scheduled", f"This backup will run: {spec.human()}"
        )
        self.accept()
