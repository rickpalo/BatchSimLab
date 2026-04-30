# QUIT BLENDER FIRST. Then run this.

$pkg     = "BlenderFoundation.Blender_ppwjx1n5r4v9t"
$virtRoot = "$env:LOCALAPPDATA\Packages\$pkg\LocalCache\Roaming\Blender Foundation\Blender\5.1\scripts\addons"
$src      = "E:\BlenderSync\SynologyDrive\ImageOfTheMonth\2018\November - Canaletto\smokeTesting\SmokeSimLabWorkspace\scripts\SmokeSimLab"

# 1. Remove the stale real-folder copy (NOT a junction, so Remove-Item is fine)
Remove-Item -LiteralPath "$virtRoot\SmokeSimLab" -Recurse -Force -ErrorAction SilentlyContinue

# 2. Clean up the leftover from the original GitHub zip install
Remove-Item -LiteralPath "$virtRoot\smokeSimulationLab-0.1.0" -Recurse -Force -ErrorAction SilentlyContinue

# 3. Create a junction at the virtual-store path pointing at your dev repo
cmd /c mklink /J "$virtRoot\SmokeSimLab" "$src"

# 4. Verify
Get-Item "$virtRoot\SmokeSimLab" | Select-Object FullName, LinkType, Target