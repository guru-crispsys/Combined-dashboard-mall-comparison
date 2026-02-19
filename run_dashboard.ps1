# Run Combined Dashboard (avoids "No pyvenv.cfg file" when using streamlit.exe on Windows)
$Root = $PSScriptRoot
Set-Location $Root
& "$Root\.venv\Scripts\python.exe" -m streamlit run main_ui.py --server.port 8501
