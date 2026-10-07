@echo off
rem Opens the desktop GUI from a source checkout. exports\ is written next to this file.
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
where pythonw >nul 2>nul && (start "" pythonw -m nte_history_exporter.gui) || (start "" pyw -3 -m nte_history_exporter.gui)
