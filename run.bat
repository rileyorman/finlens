@echo off
cd /d "%~dp0"
call venv\Scripts\activate
REM Secrets come from the encrypted SOPS store (no plaintext .env in OneDrive).
set "SOPS_AGE_KEY_FILE=C:\Users\riley\.age\keys.txt"
start chrome http://localhost:8501
sops exec-env "%USERPROFILE%\.secrets\secrets.enc.env" "streamlit run app.py --browser.serverAddress localhost"
