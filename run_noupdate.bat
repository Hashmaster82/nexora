@echo off
setlocal
echo ========================================
echo  Nexora No update and Launch
echo ========================================
echo Launching Nexora...
python -m venv myenv
myenv\Scripts\activate
python app.py
endlocal