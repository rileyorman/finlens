@echo off
call venv\Scripts\activate
start chrome http://localhost:8501
streamlit run app.py --browser.serverAddress localhost
