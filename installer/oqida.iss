; OQIDA インストーラー（Inno Setup 6）
#define AppName "OQIDA"
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{4E12AA3E-FC1E-4506-8402-7106BC1B7B93}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=mellowhq
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
; 管理者権限なしで入る（ユーザーフォルダ内）。アプリ内アップデートが確認ダイアログなしで通る。
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=OQIDA-{#AppVersion}-Setup
SetupIconFile=..\assets\oqida.ico
UninstallDisplayIcon={app}\OQIDA.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Tasks]
; checkedonce: 初回だけ自動でチェック。あとで消したショートカットが更新で復活しない。
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Files]
Source: "..\dist\OQIDA\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\OQIDA.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\OQIDA.exe"; Tasks: desktopicon

[Run]
; 通常インストール: 最後に「起動する」のチェックを出す
Filename: "{app}\OQIDA.exe"; Description: "Launch OQIDA"; Flags: nowait postinstall skipifsilent
; アプリ内アップデート（サイレント）: 終わったら自動で起動し直す
Filename: "{app}\OQIDA.exe"; Flags: nowait skipifnotsilent
