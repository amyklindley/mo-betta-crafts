@echo off
rem Builds dist\MoBettaCrafts.exe and dist\MoBettaCrafts-win64.zip (exe + install scripts + README).
rem recipes.json is baked into the exe; run "python wiki_recipes.py" first to ship fresher data.
cd /d "%~dp0"
python -m pip install --quiet -r requirements.txt pyinstaller
python make_icon.py
python -m PyInstaller --onefile --noconsole --icon icon.ico --name MoBettaCrafts --clean ^
  --add-data "recipes.json;." --hidden-import wiki_recipes crafts.py
if errorlevel 1 exit /b 1
copy /y README.md dist\ >nul
copy /y install.bat dist\ >nul
copy /y uninstall.bat dist\ >nul
del /q dist\MoBettaCrafts-win64.zip 2>nul
powershell -NoProfile -Command "Compress-Archive -Path dist\MoBettaCrafts.exe, dist\install.bat, dist\uninstall.bat, dist\README.md -DestinationPath dist\MoBettaCrafts-win64.zip"
echo.
echo Built dist\MoBettaCrafts.exe and dist\MoBettaCrafts-win64.zip
