#ifndef AppVersion
  #error AppVersion must be provided by the build
#endif
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
Source: "MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy
Source: "..\dist\CampoReader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "USER_GUIDE.md"; DestDir: "{app}"; DestName: "README.md"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal\PySide6"
Type: filesandordirs; Name: "{app}\_internal\shiboken6"
[Icons]
Name: "{group}\Campo Reader"; Filename: "{app}\CampoReader.exe"
Name: "{autodesktop}\Campo Reader"; Filename: "{app}\CampoReader.exe"; Tasks: desktopicon
Name: "{group}\Campo Reader (compatible rendering)"; Filename: "{app}\CampoReader.exe"; Parameters: "--software-rendering"
[Run]
Filename: "{app}\CampoReader.exe"; Description: "Launch Campo Reader"; Flags: nowait postinstall skipifsilent
Filename: "{app}\CampoReader.exe"; Flags: nowait runasoriginaluser; Check: IsUpdate
[Code]
function WebView2Installed: Boolean;
var Version: String;
begin
  Result := (RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM32, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM64, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;
function PrepareToInstall(var NeedsRestart: Boolean): String;
var Code: Integer;
begin
  Result := '';
  if not WebView2Installed then begin
    ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, Code) then
      Result := 'Could not start Microsoft WebView2 installation. Please check your network and retry.'
    else if not WebView2Installed then
      Result := 'Microsoft WebView2 Runtime is required. Please connect to the internet and retry the installation.';
  end;
end;

function IsUpdate: Boolean;
begin
  Result := ExpandConstant('{param:UPDATE|0}') = '1';
end;
// User data intentionally remains after uninstall/reinstall.
