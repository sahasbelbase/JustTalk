; ==============================================================================
; Inno Setup Script for Just Talk (Windows)
; Ultramodern, branded installer with dedicated uninstaller & AppUserModelID
; ==============================================================================

#define MyAppName "Just Talk"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Just Talk"
#define MyAppURL "https://github.com/sahasbelbase/JustTalk"
#define MyAppExeName "JustTalk.exe"
#define MyAppID "JustTalk.Desktop.VoiceInput.1.0"

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

; Default installation location: Per-user AppData\Programs without requiring admin UAC prompt
DefaultDirName={autopf}\Just Talk
DefaultGroupName=Just Talk
DisableProgramGroupPage=yes
AllowNoIcons=yes

; Output settings
OutputDir=..\..\dist\windows_installer
OutputBaseFilename=JustTalk-Setup-{#MyAppVersion}
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

; Clean update handling
CloseApplications=yes
RestartApplications=no
CreateUninstallRegKey=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "startupicon"; Description: "Launch Just Talk automatically on Windows startup"; GroupDescription: "Startup options:"; Flags: checkedonce

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
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"; Tasks: startupicon; AppUserModelID: "{#MyAppID}"

[Run]
; Option to launch Just Talk immediately upon completing installation
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
begin
  if CurStep = ssPostInstall then
  begin
    UninsSrc := ExpandConstant('{uninstallexe}');
    UninsDst := ExpandConstant('{app}\uninstall.exe');
    if FileExists(UninsSrc) then
    begin
      FileCopy(UninsSrc, UninsDst, False);
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
