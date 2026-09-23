@echo off
setlocal
set "DEST=%LOCALAPPDATA%\MoBettaCrafts"
echo.
echo  Mo Betta Crafts - crafting overlay for Monsters ^& Memories
echo  Installing to %DEST%
echo.
if not exist "%~dp0MoBettaCrafts.exe" (
    echo  MoBettaCrafts.exe not found next to this script. Unzip everything first.
    pause
    exit /b 1
)
taskkill /im MoBettaCrafts.exe /f >nul 2>&1
if not exist "%DEST%" mkdir "%DEST%"
copy /y "%~dp0MoBettaCrafts.exe" "%DEST%\" >nul
copy /y "%~dp0README.md" "%DEST%\" >nul
copy /y "%~dp0uninstall.bat" "%DEST%\" >nul
rem A recipes.json left by an older "Update recipes from wiki" would shadow the newer data inside the exe.
del /q "%DEST%\recipes.json" 2>nul

rem Start Menu shortcut
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Programs')+'\Mo Betta Crafts.lnk');" ^
  "$s.TargetPath='%DEST%\MoBettaCrafts.exe'; $s.WorkingDirectory='%DEST%'; $s.Description='Crafting overlay for Monsters & Memories'; $s.Save()"

echo  Installed. "Mo Betta Crafts" is in your Start Menu.
echo.
choice /c YN /m "  Start Mo Betta Crafts automatically with Windows"
if errorlevel 2 goto run
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v MoBettaCrafts /t REG_SZ /d "\"%DEST%\MoBettaCrafts.exe\"" /f >nul
echo  Added to startup. (Turn it off later from the tray icon menu.)

:run
echo.
echo  Starting it now. Look for the gold anvil icon in your system tray.
echo  Hotkey: Ctrl+Shift+K shows or hides the overlay.
start "" "%DEST%\MoBettaCrafts.exe"
timeout /t 4 >nul
endlocal
