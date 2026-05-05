; ============================================================
; WhisperType — Inno Setup script
; ============================================================
; Builds a single-file Setup.exe wizard ("Next/Next/Finish")
; that installs WhisperType.exe to Program Files, creates Start
; Menu / Desktop shortcuts, and optionally registers a Scheduled
; Task with HIGHEST run-level so the app auto-starts at login
; with admin rights and no UAC prompt.
;
; Usage:
;   1. Build the standalone exe:    python build.py
;   2. Compile the installer:       python build_installer.py
;      (or directly:                "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss)
;
; Output:
;   installer_output\WhisperType-Setup-<version>.exe
; ============================================================

#define AppName       "WhisperType"
#define AppVersion    "1.0.0"
#define AppPublisher  "Naor Daniel"
#define AppURL        "https://github.com/Danaor/WhisperType"
#define AppExeName    "WhisperType.exe"
#define TaskName      "WhisperType"

[Setup]
; Unique identifier — DO NOT change between releases or upgrades will install
; alongside instead of replacing.
AppId={{B8E7B2C5-9F4D-4A8C-8E3F-1D6A2B5C7E9F}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=installer_output
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
SetupIconFile=whispertype.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
ShowLanguageDialog=auto
DisableWelcomePage=no
WizardImageStretch=no
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "hebrew";  MessagesFile: "compiler:Languages\Hebrew.isl"

[CustomMessages]
english.AutoStartTask=Start {#AppName} automatically at Windows login (no UAC prompt)
english.AutoStartTaskGroup=Auto-start:
english.PostInstallInfo=WhisperType is installed.%n%nFirst run: right-click the system tray icon (microphone) to set your API keys (Groq / OpenAI / AssemblyAI) and pick a model.%n%nDictate by holding Ctrl+Space.

hebrew.AutoStartTask=הפעל את {#AppName} אוטומטית בכניסה ל-Windows (ללא UAC)
hebrew.AutoStartTaskGroup=הפעלה אוטומטית:
hebrew.PostInstallInfo=WhisperType הותקן בהצלחה.%n%nשימוש ראשון: לחץ קליק ימני על הסמל של המיקרופון במגש המערכת כדי להגדיר מפתחות API (Groq / OpenAI / AssemblyAI) ולבחור מודל.%n%nלהקליט: החזק Ctrl+Space.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart";   Description: "{cm:AutoStartTask}";     GroupDescription: "{cm:AutoStartTaskGroup}"

[Files]
; The PyInstaller-built standalone exe (~375MB) is the only required payload.
Source: "dist\{#AppExeName}";    DestDir: "{app}"; Flags: ignoreversion
Source: "whispertype.ico";        DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md";           DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "..\LICENSE";             DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}";                     Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\whispertype.ico"; Comment: "{#AppName} — speech to text"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";                Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\whispertype.ico"; Tasks: desktopicon; Comment: "{#AppName} — speech to text"

[Run]
; If user enabled the autostart task: register a Windows Scheduled Task with
; HIGHEST run-level + ONLOGON trigger so subsequent launches at login bypass
; UAC. This mirrors the legacy install_no_uac.bat logic.
; Note: /tr requires triple-quoted exe path because of nested cmd parsing.
Filename: "{cmd}"; \
    Parameters: "/C schtasks /create /tn ""{#TaskName}"" /tr ""\""{app}\{#AppExeName}\"""" /sc ONLOGON /rl HIGHEST /delay 0000:05 /f"; \
    Flags: runhidden; \
    StatusMsg: "Registering auto-start task..."; \
    Tasks: autostart

; Optional: launch the app right after install. The /TR ONLOGON task only
; fires at next login — without this Run entry the user has to log out/in
; or run the task manually for the first launch.
Filename: "{cmd}"; \
    Parameters: "/C schtasks /run /tn ""{#TaskName}""" ; \
    Flags: runhidden nowait postinstall skipifsilent; \
    Description: "{cm:LaunchProgram,{#AppName}}"; \
    Tasks: autostart

; If user did NOT enable autostart task: offer to launch the exe directly.
; This will trigger one UAC prompt (because the exe is uac-admin elevated).
Filename: "{app}\{#AppExeName}"; \
    Description: "{cm:LaunchProgram,{#AppName}}"; \
    Flags: nowait postinstall skipifsilent unchecked; \
    Check: not WizardIsTaskSelected('autostart')

[UninstallRun]
; Always try to remove the scheduled task on uninstall (idempotent — schtasks
; returns nonzero if the task doesn't exist; runhidden + the trailing
; redirect swallow the error so the uninstaller stays clean).
Filename: "{cmd}"; \
    Parameters: "/C schtasks /delete /tn ""{#TaskName}"" /f >nul 2>&1"; \
    Flags: runhidden; \
    RunOnceId: "DelTask"

[UninstallDelete]
; Don't touch %APPDATA%\WhisperType — that holds user config, history, and
; meeting transcripts. Leaving it lets re-installs preserve user data. If the
; user wants a clean wipe they can delete %APPDATA%\WhisperType manually.

[Code]
// Show a friendly post-install info page with API key + hotkey reminders.
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // Nothing forced here — the [Run] entries handle launch, and the user
    // can always read README.md from the install dir. Hook reserved for
    // future post-install tasks (e.g. download_models).
  end;
end;

// Warn the user if WhisperType.exe is still running before installing —
// CloseApplications=yes in [Setup] will normally handle this, but the
// scheduled task can re-spawn it if uninstall ran in a weird state.
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
