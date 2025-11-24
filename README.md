ESPHome LVGL display for Home Assistant

Extends https://github.com/agillis/esphome-modular-lvgl-buttons (Copyright (c) 2024 Andrew Gillis)

## ESPHome Setup

1. Create/activate the project virtual environment (PowerShell example):
	```powershell
	& .\.venv\Scripts\Activate.ps1
	```
2. Make sure `pip` itself is current so it can pull the latest wheels:
	```powershell
	python -m pip install --upgrade pip
	```
3. Install the required Python packages (adds the ESPHome CLI entry point):
	```powershell
	python -m pip install -r packages.txt
	```
	If you prefer the dashboard UI, use `python -m pip install "esphome[dashboard]"` instead of the requirements file.
4. Verify the installation before building firmware:
	```powershell
	python -m esphome version
	```
	A semantic version string confirms the CLI is available; an error about `esphome.__main__` indicates the install did not succeed.
5. Build/flash your node:
	```powershell
	python -m esphome run custom_slider.yaml
	```

Troubleshooting tips:
- Ensure VS Code and ESPHome are both pointing to the same virtual environment (`Ctrl+Shift+P` → `Python: Select Interpreter`).
- Re-run step 3 if the environment changes or the dependency cache is cleared.
