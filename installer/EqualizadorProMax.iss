#define MyAppName "Equalizador ProMax"
#define MyAppVersion "0.1.9"
#define MyAppPublisher "FabricaBots"
#define MyAppExeName "EqualizadorProMax.exe"
#define MyAppExePath "..\dist\EqualizadorProMax.exe"
#define MyAppIconPath "app.ico"

[Setup]
AppId={{E9A6E4B6-6D30-4E3B-B48F-9F3D2B4A5C20}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName}
DefaultDirName={autopf}\Equalizador ProMax
DefaultGroupName={#MyAppName}
OutputDir=dist-installer
OutputBaseFilename=EqualizadorProMax-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
#if FileExists(MyAppIconPath)
SetupIconFile={#MyAppIconPath}
#endif

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Files]
Source: "{#MyAppExePath}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir Equalizador ProMax"; Flags: nowait postinstall skipifsilent
