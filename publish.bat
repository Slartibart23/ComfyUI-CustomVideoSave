@echo off
REM Publishes this node to the Comfy Registry. You will be asked for your API key.
pip install --upgrade comfy-cli
comfy node publish
pause
