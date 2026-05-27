@echo off
REM ===========================================================================
REM run_bg_probe.bat - background-bake resume experiment (BUG-010)
REM
REM Runs bg_resume_probe.py TWICE in TRUE background with --factory-startup:
REM   RUN 1 bakes frames 1-100 into a throwaway cache (creates the partial).
REM   RUN 2 bakes 1-200 - THE TEST: read its VERDICT line.
REM
REM --factory-startup is REQUIRED: without it your user add-ons (polygoniq engon,
REM memsaver) load and flood the console, and the worker itself always bakes with
REM --factory-startup, so this matches the real environment.
REM
REM If any path below is wrong on your machine, edit the four SET lines.
REM ===========================================================================
setlocal

set "BLENDER=C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
set "BLEND=E:\BlenderSync\SynologyDrive\ImageOfTheMonth\2018\November - Canaletto\SmokeSimulatorForPiazzoSanMarco.blend"
set "SCRIPT=%~dp0bg_resume_probe.py"
set "CACHE=E:\BlenderSync\SynologyDrive\ImageOfTheMonth\2018\November - Canaletto\smokeTesting\bg_probe_cache"
set "DOMAIN=Smoke Domain"

echo === Clearing probe cache for a fresh start: "%CACHE%"
if exist "%CACHE%" rmdir /s /q "%CACHE%"

echo.
echo ============ RUN 1: bake frames 1-100 (build the partial cache) ============
"%BLENDER%" --background "%BLEND%" --factory-startup --python "%SCRIPT%" -- "%CACHE%" 100 "%DOMAIN%"

echo.
echo ============ RUN 2: bake frames 1-200 (THE TEST - does it resume?) =========
"%BLENDER%" --background "%BLEND%" --factory-startup --python "%SCRIPT%" -- "%CACHE%" 200 "%DOMAIN%"

echo.
echo ===========================================================================
echo Done. Scroll up to RUN 2 and read the line:  [bg_probe] VERDICT: ...
echo   RESUMED        = background gives true partial resume (redesign is worth it)
echo   REBAKED-FROM-1 = background re-bakes too (efficiency only)
echo   WIPED-ON-ASSIGN= assignment wiped the cache (merge needs work)
echo ===========================================================================
pause
