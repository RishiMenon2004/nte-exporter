@echo off
rem Opens the desktop GUI from a source checkout. exports\ is written next to this file.
rem Needs the GUI dependencies: pip install -e ".[gui]"
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
if exist ".venv\Scripts\pythonw.exe" (start "" ".venv\Scripts\pythonw.exe" -m nte_history_exporter.gui & exit /b)
where pythonw >nul 2>nul && (start "" pythonw -m nte_history_exporter.gui) || (start "" pyw -3 -m nte_history_exporter.gui)
