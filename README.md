# Minecraft Offline Launcher

A Windows-friendly Minecraft offline launcher built with Python, PySide6, and
`minecraft-launcher-lib`.

## Features

- Version dropdown populated from Mojang's version manifest
- Software dropdown: Vanilla, Fabric, Forge, NeoForge, OptiFine
- Offline username field
- Offline or Microsoft account mode
- RAM allocation slider
- Dark modern PySide6 interface
- Download/install progress with percentage plus MB totals when the backend reports byte totals
- Saved profiles with quick switching, create, save, delete, and open-folder controls
- Separate Minecraft directory per profile, so each profile has its own `mods`, `config`, `saves`, and resource folders
- Launch button that installs missing files and starts Minecraft
- PyInstaller spec for a single-file Windows executable

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Run

```powershell
python main.py
```

Or double-click `run_launcher.bat`.

## Build Single EXE

```powershell
pyinstaller MinecraftOfflineLauncher.spec
```

The executable will be created in `dist\MinecraftOfflineLauncher.exe`.

Or double-click `build_exe.bat`.

## Requirements

- Windows 10 or 11
- Python 3.11 or newer installed from python.org
- Internet access for the first install of Minecraft versions, mod loaders, and Python packages
- Java installed and available on PATH for game launch

## Profiles and Mods

Each profile gets its own directory under:

```text
%APPDATA%\MinecraftOfflineLauncher\profile_directories
```

Use `Open Folder` in the launcher to open the selected profile directory. Put
mods into that profile's `mods` folder.

## Microsoft Login

Microsoft login requires your own Azure application Client ID and redirect URI.
The Minecraft authentication API does not provide a public launcher-wide client
ID. Create an Azure application, apply for Minecraft API permission if needed,
enter the Client ID in the launcher, then click `Login Microsoft`.

## OptiFine

`minecraft-launcher-lib` does not currently provide an OptiFine installer module.
The launcher can run an OptiFine profile if it already exists inside that
profile's directory, but it cannot install OptiFine automatically.

## Notes

Offline mode is for local/offline play. Microsoft mode uses a paid account and
does not bypass ownership, online multiplayer authentication, or server-side
checks.
