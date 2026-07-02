@echo off
call "%~dp0venv\Scripts\activate"
streamlit run "%~dp0app.py" --server.headless true --server.address localhost --browser.serverAddress localhost --server.port 8501
