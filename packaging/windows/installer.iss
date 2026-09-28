; Inno Setup Script for Just Talk (Windows)
; Ensures AppUserModelID is configured so Taskbar Pinning NEVER reverts to Python!

#define MyAppName "Just Talk"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Just Talk Team"
#define MyAppURL "https://github.com/justtalk/justtalk"
#define MyAppExeName "JustTalk.exe"
#define MyAppID "justtalk.desktop.voiceinput.1.0"

[Setup]
AppId={{8B3E42D7-2F6B-4D3B-9024-C9A1A7FE6721}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\Just Talk
DefaultGroupName=Just Talk
AllowNoIcons=yes
OutputDir=dist\windows_installer
OutputBaseFilename=JustTalk-Setup-{#MyAppVersion}
SetupIconFile=..\..\just_talk\assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startupicon"; Description: "Launch Just Talk on Windows startup"; GroupDescription: "Startup options:"

[Files]
Source: "..\..\dist\JustTalk\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\JustTalk\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\just_talk\assets\icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Start Menu Shortcut with explicit AppUserModelID
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"; AppUserModelID: "{#MyAppID}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
; Desktop Shortcut with explicit AppUserModelID
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon; AppUserModelID: "{#MyAppID}"
; Startup Shortcut
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"; Tasks: startupicon; AppUserModelID: "{#MyAppID}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
