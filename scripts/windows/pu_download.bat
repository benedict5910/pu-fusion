@echo off
REM Paderborn bearing data (CC BY-NC 4.0) - download with Windows' built-in curl, no Python needed.
REM   pu_download.bat            -> starter subset: 12 archives (K001-K004, KA04 KA15 KA16 KA22, KI04 KI14 KI16 KI18), ~1.9 GB
REM   pu_download.bat all        -> all 32 official archives, ~5.1 GB
REM File list verified against https://groups.uni-paderborn.de/kat/BearingDataCenter/ on 21 Oct 2026.
REM Safe to re-run: partial files resume, finished files are skipped. Leave the window open.
title Paderborn download - leave this window open
set "LIST=%~dp0pu_list_starter.txt"
if /I "%1"=="all" set "LIST=%~dp0pu_list_all.txt"
set "DEST=%USERPROFILE%\Downloads\paderborn"
if not exist "%DEST%" mkdir "%DEST%"
cd /d "%DEST%"
echo started %DATE% %TIME% list=%LIST% > _status.txt
curl.exe --fail --location --retry 5 --retry-delay 5 --continue-at - --parallel --parallel-max 3 --progress-bar --config "%LIST%"
echo curl_exit=%ERRORLEVEL% >> _status.txt
dir /-C *.rar >> _status.txt
echo finished %DATE% %TIME% >> _status.txt
echo DONE > _done.txt
echo.
echo Finished. You can close this window.
pause
