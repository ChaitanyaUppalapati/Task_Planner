; Inno Setup script - per-user install, no admin rights required.
; Build: iscc /DAppVersion=1.0.0 packaging\installer.iss

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6C2F4E1B-8C9A-4E57-9A43-7B1D2E3F4A5C}
AppName=Task Planner
AppVersion={#AppVersion}
AppPublisher=Chaitanya Uppalapati
AppCopyright=Copyright (c) 2026 Chaitanya Uppalapati. All rights reserved.
LicenseFile=..\LICENSE
DefaultDirName={localappdata}\Programs\TaskPlanner
DefaultGroupName=Task Planner
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=TaskPlannerSetup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\TaskPlanner.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "autostart"; Description: "Start Task Planner when I sign in (recommended for automatic tracking)"; GroupDescription: "Tracking:"

[Files]
Source: "..\dist\TaskPlanner\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Task Planner"; Filename: "{app}\TaskPlanner.exe"
Name: "{userdesktop}\Task Planner"; Filename: "{app}\TaskPlanner.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "TaskPlanner"; ValueData: """{app}\TaskPlanner.exe"" --minimized"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\TaskPlanner.exe"; Description: "Launch Task Planner"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM TaskPlanner.exe /F"; Flags: runhidden; RunOnceId: "KillApp"
