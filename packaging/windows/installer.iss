; ==============================================================================
; Inno Setup Script for Just Talk (Windows)
; Ultramodern, branded installer with dedicated uninstaller & AppUserModelID
; ==============================================================================

#define MyAppName "Just Talk"
#define MyAppVersion "2.3.0"
#define MyAppPublisher "Just Talk"
#define MyAppURL "https://github.com/sahasbelbase/JustTalk"
#define MyAppExeName "JustTalk.exe"
#define MyAppID "JustTalk.Desktop.VoiceInput.2.0"

[Setup]
; Unique GUID for Just Talk
AppId={{8B3E42D7-2F6B-4D3B-9024-C9A1A7FE6721}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Default installation location: Per-user AppData\Programs (prevents CreateFile Code 5 Access Denied)
DefaultDirName={localappdata}\Programs\Just Talk
DefaultGroupName=Just Talk
DisableProgramGroupPage=yes
AllowNoIcons=yes

; 64-bit architecture
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Output settings: standard predictable name for releases
OutputDir=..\..\dist\windows_installer
OutputBaseFilename=JustTalk-Windows
SetupIconFile=..\..\just_talk\assets\icon.ico
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\icon.ico

; Modern Wizard Styling & High-Resolution Artwork
WizardStyle=modern
WizardSizePercent=115,115
WizardResizable=no
WizardImageFile=wizard_sidebar.bmp
WizardSmallImageFile=wizard_small.bmp

; Compression
Compression=lzma2/ultra64
SolidCompression=yes

; User Privileges: Lowest (installs in user space without requiring administrator password)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Clean update handling: force close running JustTalk process to avoid locked file errors
CloseApplications=force
CloseApplicationsFilter=*JustTalk*
RestartApplications=no
CreateUninstallRegKey=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "startupicon"; Description: "Launch Just Talk automatically on Windows startup"; GroupDescription: "Startup options:"; Flags: checkedonce
Name: "downloadmodel"; Description: "Pre-download on-device Whisper model (~460 MB) for instant offline speech & live streaming"; GroupDescription: "Speech Models:"; Flags: checkedonce

[Files]
; Main application binaries produced by PyInstaller
Source: "..\..\dist\JustTalk\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\JustTalk\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\just_talk\assets\icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Start Menu primary shortcut with explicit AppUserModelID (prevents generic Python taskbar grouping)
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"; AppUserModelID: "{#MyAppID}"
; Start Menu dedicated Uninstaller shortcut
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"; IconFilename: "{app}\icon.ico"
; Standalone Uninstaller shortcut inside application directory
Name: "{app}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"; IconFilename: "{app}\icon.ico"
; Desktop Shortcut
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon; AppUserModelID: "{#MyAppID}"
; Startup Shortcut
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--minimized"; IconFilename: "{app}\icon.ico"; Tasks: startupicon; AppUserModelID: "{#MyAppID}"

[Run]
; Option to launch Just Talk immediately upon completing installation (opens app with live download progress if needed)
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up runtime logs and temporary files on uninstallation
Type: files; Name: "{app}\*.log"
Type: files; Name: "{app}\*.tmp"
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
// Duplicate unins000.exe to uninstall.exe for users looking for an uninstall.exe binary directly
procedure CurStepChanged(CurStep: TSetupStep);
var
  UninsSrc, UninsDst: String;
  ModelDir, PsScript: String;
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    UninsSrc := ExpandConstant('{uninstallexe}');
    UninsDst := ExpandConstant('{app}\uninstall.exe');
    if FileExists(UninsSrc) then
    begin
      FileCopy(UninsSrc, UninsDst, False);
    end;

    // Optional setup download for on-device Whisper model
    if WizardIsTaskSelected('downloadmodel') then
    begin
      ModelDir := ExpandConstant('{localappdata}\JustTalk\models\small');
      if not DirExists(ModelDir) then
      begin
        PsScript := 'powershell -NoProfile -WindowStyle Hidden -Command "' +
          '$dest = [System.IO.Path]::Combine($env:LOCALAPPDATA, ''JustTalk\models\small''); ' +
          'if (-not (Test-Path $dest)) { New-Item -ItemType Directory -Force -Path $dest | Out-Null; ' +
          'Invoke-WebRequest -Uri ''https://huggingface.co/Systran/faster-whisper-small/resolve/main/config.json'' -OutFile (Join-Path $dest ''config.json'') -UseBasicParsing; ' +
          'Invoke-WebRequest -Uri ''https://huggingface.co/Systran/faster-whisper-small/resolve/main/tokenizer.json'' -OutFile (Join-Path $dest ''tokenizer.json'') -UseBasicParsing; ' +
          'Invoke-WebRequest -Uri ''https://huggingface.co/Systran/faster-whisper-small/resolve/main/vocabulary.txt'' -OutFile (Join-Path $dest ''vocabulary.txt'') -UseBasicParsing; ' +
          'Invoke-WebRequest -Uri ''https://huggingface.co/Systran/faster-whisper-small/resolve/main/model.bin'' -OutFile (Join-Path $dest ''model.bin'') -UseBasicParsing; }' +
          '"';
        Exec('cmd.exe', '/c start /b ' + PsScript, '', SW_HIDE, ewNoWait, ResultCode);
      end;
    end;
  end;
end;


// Ask user if they wish to purge configuration and history data upon uninstallation
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  UserDataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    UserDataDir := ExpandConstant('{localappdata}\JustTalk');
    if DirExists(UserDataDir) then
    begin
      if MsgBox('Do you also want to remove all personal Just Talk history and local configuration settings?', mbConfirmation, MB_YESNO) = IDYES then
      begin
        DelTree(UserDataDir, True, True, True);
      end;
    end;
  end;
end;
