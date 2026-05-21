@echo off
echo Setting up Financial Statement Analyzer...
python -m venv venv
call venv\Scripts\activate
pip install -r requirements.txt
echo.
echo Setup complete! Run run.bat to start the app.
pause
