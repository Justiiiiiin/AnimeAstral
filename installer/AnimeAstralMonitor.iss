; Inno Setup 6 – installer for Anime Astral Monitor
; Call (from the GitHub build):  ISCC.exe /DAppVersion=0.5.0 installer\AnimeAstralMonitor.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Anime Astral Monitor"
#define AppExe "AnimeAstralMonitor.exe"

[Setup]
; Fixed ID: new versions replace the old one instead of installing next to it
AppId={{B7C1D0A4-5E2F-4C8B-9A3D-1F6E2A7C4D90}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Anime Astral Monitor
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Install for the current user only: no administrator prompt
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=AnimeAstralMonitor-Setup-{#AppVersion}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
; the Windows display language decides; English for everything that isn't German
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[CustomMessages]
english.SafeMode=safe mode
german.SafeMode=abgesichert

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\AnimeAstralMonitor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[UninstallDelete]
; Small updates swap files without the installer – remove the whole program folder when uninstalling
; (settings and statistics are in %APPDATA% and are kept)
Type: filesandordirs; Name: "{app}"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autoprograms}\{#AppName} ({cm:SafeMode})"; Filename: "{app}\{#AppExe}"; Parameters: "--safe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; Refresh the Windows icon cache (otherwise shortcuts still show the old logo)
Filename: "{sys}\ie4uinit.exe"; Parameters: "-show"; Flags: runhidden nowait skipifdoesntexist
; Normal installation: launch option at the end
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent runasoriginaluser
; Automatic update (silent): start the program again afterwards
Filename: "{app}\{#AppExe}"; Flags: nowait runasoriginaluser; Check: RelaunchRequested

[Code]
// The program starts the installer for updates with /relaunch=1
function RelaunchRequested: Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/relaunch=1') = 0 then
      Result := True;
end;
