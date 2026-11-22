; TaskPill Windows installer (Inno Setup 6).
; Build: ISCC /DAppVersion=0.1.0 packaging\installer.iss   (after PyInstaller made dist\TaskPill)
;
; * Installs for the current user only (no admin prompt) into
;   %LOCALAPPDATA%\Programs\TaskPill, so the hook path stays stable.
; * Uninstall first stops the app, then removes TaskPill's hooks from
;   ~/.claude/settings.json (TaskPill.exe --disconnect makes a backup first).
; * The user's TaskPill settings (%APPDATA%\TaskPill) are kept.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F3B0C8E-2B4D-4C61-9C1A-7E5D2A9B1F40}
AppName=TaskPill
AppVersion={#AppVersion}
AppVerName=TaskPill {#AppVersion}
AppPublisher=Manasvi Mittal
AppComments=A status pill for Claude Code
DefaultDirName={localappdata}\Programs\TaskPill
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=TaskPill-Setup-{#AppVersion}-Windows
SetupIconFile=taskpill.ico
UninstallDisplayIcon={app}\TaskPill.exe
UninstallDisplayName=TaskPill
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\TaskPill\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\TaskPill"; Filename: "{app}\TaskPill.exe"; Comment: "A status pill for Claude Code"

[Run]
Filename: "{app}\TaskPill.exe"; Description: "Start TaskPill"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM TaskPill.exe"; Flags: runhidden; RunOnceId: "StopApp"
Filename: "{app}\TaskPill.exe"; Parameters: "--disconnect"; Flags: runhidden waituntilterminated; RunOnceId: "Disconnect"
