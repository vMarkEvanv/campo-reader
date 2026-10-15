#define AppVersion "1.0.0"
[Setup]
AppId={{78C997E0-ECE3-4CB6-981C-79F378C3E203}
AppName=Campo Reader
AppVersion={#AppVersion}
AppPublisher=Campo Reader
DefaultDirName={localappdata}\Programs\CampoReader
DefaultGroupName=Campo Reader
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\release
OutputBaseFilename=CampoReader-Setup-Windows-x64
SetupIconFile=campo.ico
UninstallDisplayIcon={app}\CampoReader.exe
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: checkedonce
[Files]
Source: "..\dist\CampoReader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{group}\Campo Reader"; Filename: "{app}\CampoReader.exe"
Name: "{autodesktop}\Campo Reader"; Filename: "{app}\CampoReader.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\CampoReader.exe"; Description: "Launch Campo Reader"; Flags: nowait postinstall skipifsilent
; User data intentionally remains after uninstall/reinstall.
