; ==============================================================================
; NSIS Modern UI 2 Installer Script for Just Talk (Windows)
; Creates JustTalk-Setup.exe with dedicated Uninstall.exe and custom branding
; ==============================================================================

Unicode true
ManifestDPIAware true

!define PRODUCT_NAME "Just Talk"
!define PRODUCT_VERSION "2.0.1"
!define PRODUCT_PUBLISHER "Just Talk"
!define PRODUCT_WEB_SITE "https://github.com/sahasbelbase/JustTalk"
!define PRODUCT_EXE "JustTalk.exe"
!define PRODUCT_DIR_REGKEY "Software\Microsoft\Windows\CurrentVersion\App Paths\JustTalk.exe"
!define PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\JustTalk"
!define PRODUCT_APP_USER_MODEL_ID "JustTalk.Desktop.VoiceInput.1.0"

; Output settings
Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "..\..\dist\windows_installer\JustTalk-Setup-${PRODUCT_VERSION}-nsis.exe"
InstallDir "$LOCALAPPDATA\Programs\Just Talk"
InstallDirRegKey HKCU "${PRODUCT_DIR_REGKEY}" ""
RequestExecutionLevel user
SetCompressor /SOLID lzma

; Includes
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"

; Modern UI Configuration
!define MUI_ICON "..\..\just_talk\assets\icon.ico"
!define MUI_UNICON "..\..\just_talk\assets\icon.ico"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "wizard_small.bmp"
!define MUI_HEADERIMAGE_RIGHT
!define MUI_WELCOMEFINISHPAGE_BITMAP "wizard_sidebar.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "wizard_sidebar.bmp"
!define MUI_ABORTWARNING

; Welcome Page
!define MUI_WELCOMEPAGE_TITLE "Welcome to Just Talk"
!define MUI_WELCOMEPAGE_TEXT "Just Talk gives you instantaneous, frictionless AI voice dictation across all your Windows applications.$\r$\n$\r$\nPress any shortcut to talk, transcribe locally with Whisper, and format with your preferred AI model."
!insertmacro MUI_PAGE_WELCOME

; Directory Page
!insertmacro MUI_PAGE_DIRECTORY

; Components / Options Page
!insertmacro MUI_PAGE_COMPONENTS

; Instfiles Page
!insertmacro MUI_PAGE_INSTFILES

; Finish Page
!define MUI_FINISHPAGE_RUN "$INSTDIR\${PRODUCT_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Launch Just Talk now"
!insertmacro MUI_PAGE_FINISH

; Uninstaller Pages
!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

; Language
!insertmacro MUI_LANGUAGE "English"

; ------------------------------------------------------------------------------
; Installer Sections
; ------------------------------------------------------------------------------

Section "Just Talk Core (Required)" SecCore
    SectionIn RO
    SetOutPath "$INSTDIR"
    SetOverwrite on

    ; Copy application files from PyInstaller dist directory
    File /r "..\..\dist\JustTalk\*.*"
    File "..\..\just_talk\assets\icon.ico"

    ; Create dedicated uninstaller executable in the application folder
    WriteUninstaller "$INSTDIR\Uninstall.exe"

    ; Start Menu Shortcuts
    CreateDirectory "$SMPROGRAMS\Just Talk"
    CreateShortcut "$SMPROGRAMS\Just Talk\Just Talk.lnk" "$INSTDIR\${PRODUCT_EXE}" "" "$INSTDIR\icon.ico" 0 SW_SHOWNORMAL "" "Just Talk AI Voice Dictation"
    CreateShortcut "$SMPROGRAMS\Just Talk\Uninstall Just Talk.lnk" "$INSTDIR\Uninstall.exe" "" "$INSTDIR\icon.ico" 0 SW_SHOWNORMAL "" "Uninstall Just Talk"

    ; Register AppUserModelID for Windows 10/11 taskbar pinning
    WriteRegStr HKCU "Software\Classes\AppUserModelId\${PRODUCT_APP_USER_MODEL_ID}" "DisplayName" "${PRODUCT_NAME}"
    WriteRegStr HKCU "Software\Classes\AppUserModelId\${PRODUCT_APP_USER_MODEL_ID}" "IconUri" "$INSTDIR\icon.ico"

    ; Registry keys for Add/Remove Programs (Control Panel & Windows Settings)
    WriteRegStr HKCU "${PRODUCT_DIR_REGKEY}" "" "$INSTDIR\${PRODUCT_EXE}"
    WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "DisplayName" "${PRODUCT_NAME}"
    WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
    WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
    WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "DisplayIcon" "$INSTDIR\icon.ico"
    WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
    WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "URLInfoAbout" "${PRODUCT_WEB_SITE}"
    WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
    WriteRegDWORD HKCU "${PRODUCT_UNINST_KEY}" "NoModify" 1
    WriteRegDWORD HKCU "${PRODUCT_UNINST_KEY}" "NoRepair" 1

    ; Estimate installed size
    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    IntFmt $0 "0x%08X" $0
    WriteRegDWORD HKCU "${PRODUCT_UNINST_KEY}" "EstimatedSize" "$0"
SectionEnd

Section "Desktop Shortcut" SecDesktop
    CreateShortcut "$DESKTOP\Just Talk.lnk" "$INSTDIR\${PRODUCT_EXE}" "" "$INSTDIR\icon.ico" 0 SW_SHOWNORMAL "" "Just Talk AI Voice Dictation"
SectionEnd

Section "Start on Windows Startup" SecStartup
    CreateShortcut "$SMSTARTUP\Just Talk.lnk" "$INSTDIR\${PRODUCT_EXE}" "--background" "$INSTDIR\icon.ico" 0 SW_SHOWNORMAL "" "Just Talk Background Service"
SectionEnd

; Section Descriptions
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
    !insertmacro MUI_DESCRIPTION_TEXT ${SecCore} "Installs the Just Talk engine, local Whisper model, and core runtime files."
    !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "Creates a quick-access shortcut on your desktop."
    !insertmacro MUI_DESCRIPTION_TEXT ${SecStartup} "Launches Just Talk in the background when Windows boots up so push-to-talk is always ready."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; ------------------------------------------------------------------------------
; Uninstaller Section
; ------------------------------------------------------------------------------

Section "Uninstall"
    ; Remove shortcuts
    Delete "$DESKTOP\Just Talk.lnk"
    Delete "$SMSTARTUP\Just Talk.lnk"
    Delete "$SMPROGRAMS\Just Talk\Just Talk.lnk"
    Delete "$SMPROGRAMS\Just Talk\Uninstall Just Talk.lnk"
    RMDir "$SMPROGRAMS\Just Talk"

    ; Ask user whether to delete local config & history
    MessageBox MB_YESNO|MB_ICONQUESTION "Do you also want to remove your local Just Talk configuration settings and history?" IDNO skip_purge
    RMDir /r "$LOCALAPPDATA\JustTalk"
skip_purge:

    ; Clean up installation files
    RMDir /r "$INSTDIR"

    ; Clean up registry keys
    DeleteRegKey HKCU "${PRODUCT_UNINST_KEY}"
    DeleteRegKey HKCU "${PRODUCT_DIR_REGKEY}"
    DeleteRegKey HKCU "Software\Classes\AppUserModelId\${PRODUCT_APP_USER_MODEL_ID}"
SectionEnd
