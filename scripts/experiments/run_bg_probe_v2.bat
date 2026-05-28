@echo off
REM ===========================================================================
REM run_bg_probe_v2.bat — TODO-35 probe (user's "save tmp .blend with
REM cache_directory pointing at populated dir, then reload" resume approach).
REM
REM Three sequential --background --factory-startup Blender invocations:
REM   STEP A (setup)   — bake 100 frames fresh into <cache>.
REM   STEP B (prepare) — move <cache> → <tmp_cache>; assign cache_directory =
REM                       <tmp_cache>; save <tmp_blend>.
REM   STEP C (test)    — open <tmp_blend>; bake to 200; report mtime
REM                       preservation; print VERDICT.
REM
REM Look for "VERDICT:" lines in STEP B (early WIPED-ON-ASSIGN) and STEP C
REM (final RESUMED / REBAKED-FROM-1 / WIPED / NO PRIOR FRAMES).
REM ===========================================================================
setlocal

set "BLENDER=C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
set "BLEND=E:\BlenderSync\SynologyDrive\ImageOfTheMonth\2018\November - Canaletto\SmokeSimulatorForPiazzoSanMarco.blend"
set "SCRIPT=%~dp0bg_resume_probe_v2.py"
set "CACHE=E:\BlenderSync\SynologyDrive\ImageOfTheMonth\2018\November - Canaletto\smokeTesting\bg_probe_v2_cache"
set "TMP_CACHE=E:\BlenderSync\SynologyDrive\ImageOfTheMonth\2018\November - Canaletto\smokeTesting\bg_probe_v2_cache_tmp"
set "TMP_BLEND=E:\BlenderSync\SynologyDrive\ImageOfTheMonth\2018\November - Canaletto\smokeTesting\bg_probe_v2.blend"
set "DOMAIN=Smoke Domain"

echo === Cleaning previous probe state ===
if exist "%CACHE%"     rmdir /s /q "%CACHE%"
if exist "%TMP_CACHE%" rmdir /s /q "%TMP_CACHE%"
if exist "%TMP_BLEND%" del   /q    "%TMP_BLEND%"

echo.
echo ============ STEP A: bake 100 frames into the test cache ============
"%BLENDER%" --background "%BLEND%" --factory-startup --python "%SCRIPT%" -- setup "%CACHE%" 100 "%DOMAIN%"
if errorlevel 1 (echo STEP A FAILED & pause & exit /b 1)

echo.
echo ============ STEP B: move + repoint + save tmp .blend (4-step prep) ============
"%BLENDER%" --background "%BLEND%" --factory-startup --python "%SCRIPT%" -- prepare "%CACHE%" "%TMP_CACHE%" "%TMP_BLEND%" "%DOMAIN%"
if errorlevel 1 (echo STEP B FAILED & pause & exit /b 1)

echo.
echo ============ STEP C: open tmp .blend + bake to 200 + report ============
"%BLENDER%" --background "%TMP_BLEND%" --factory-startup --python "%SCRIPT%" -- test "%TMP_CACHE%" 200
if errorlevel 1 (echo STEP C FAILED & pause & exit /b 1)

echo.
echo ===========================================================================
echo Look for VERDICT lines in STEP B and STEP C above:
echo   RESUMED         = save+reload trick works -> fixes BUG-010
echo   REBAKED-FROM-1  = load-time scan didn't detect existing frames
echo   WIPED-ON-ASSIGN = cache_directory assign wiped the moved files (BUG-004
echo                     applies to a populated new dir too)
echo   NO PRIOR FRAMES = empty tmp cache by test time (check STEP B output)
echo ===========================================================================
pause
