; Inno Setup 6 – Installer für Anime Astral Monitor
; Aufruf (vom GitHub-Build):  ISCC.exe /DAppVersion=0.5.0 installer\AnimeAstralMonitor.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Anime Astral Monitor"
#define AppExe "AnimeAstralMonitor.exe"

[Setup]
; Feste Kennung: neue Versionen ersetzen die alte statt daneben zu installieren
AppId={{B7C1D0A4-5E2F-4C8B-9A3D-1F6E2A7C4D90}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Anime Astral Monitor
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Installation nur für den aktuellen Benutzer: keine Administrator-Abfrage
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
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\AnimeAstralMonitor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[UninstallDelete]
; Kleine Updates tauschen Dateien ohne Installer aus – beim Deinstallieren den ganzen Programmordner entfernen
; (Einstellungen und Statistik liegen in %APPDATA% und bleiben erhalten)
Type: filesandordirs; Name: "{app}"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; Normale Installation: Startoption am Ende
Filename: "{app}\{#AppExe}"; Description: "{#AppName} starten"; Flags: nowait postinstall skipifsilent runasoriginaluser
; Automatisches Update (leise): Programm danach wieder starten
Filename: "{app}\{#AppExe}"; Flags: nowait runasoriginaluser; Check: RelaunchRequested

[Code]
// Das Programm startet den Installer bei Updates mit /relaunch=1
function RelaunchRequested: Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/relaunch=1') = 0 then
      Result := True;
end;
