@echo off
setlocal
set "DEST=%LOCALAPPDATA%\MoBettaCrafts"
echo.
echo  Removing Mo Betta Crafts from %DEST%
taskkill /im MoBettaCrafts.exe /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v MoBettaCrafts /f >nul 2>&1
del /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Mo Betta Crafts.lnk" 2>nul
choice /c YN /m "  Also delete your pinned recipes and count corrections (crafts_state.json)"
if errorlevel 2 (
    del /q "%DEST%\MoBettaCrafts.exe" "%DEST%\README.md" "%DEST%\MoBettaCrafts.log" "%DEST%\recipes.json" 2>nul
    echo  Kept %DEST%\crafts_state.json
) else (
    cd /d "%TEMP%"
    rmdir /s /q "%DEST%" 2>nul
)
echo.
echo  Done.
pause
endlocal
