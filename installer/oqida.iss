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

[Languages]
; 日本語を既定にして、英語も選べるようにする
Name: "ja"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
ja.CreateDesktopIcon=デスクトップにショートカットを作成する
ja.LaunchApp=OQIDA を起動する
ja.InstallingWebView2=画面表示に必要な部品（WebView2）をインストールしています...
ja.WebView2Failed=WebView2 のインストールに失敗しました。OQIDA の画面が表示されない場合は、Microsoft の「Edge WebView2 ランタイム」を手動でインストールしてください。
en.CreateDesktopIcon=Create a desktop shortcut
en.LaunchApp=Launch OQIDA
en.InstallingWebView2=Installing a required component (WebView2)...
en.WebView2Failed=WebView2 could not be installed. If OQIDA shows a blank window, please install the Microsoft Edge WebView2 Runtime manually.

[Tasks]
; checkedonce: 初回だけ自動でチェック。あとで消したショートカットが更新で復活しない。
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "..\dist\OQIDA\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; WebView2 の導入に使う公式インストーラー（ネットから取得してくる。なければWebView2の自動導入は飛ばす）
Source: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: external deleteafterinstall; Check: WebView2Missing and WebView2Downloaded

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\OQIDA.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\OQIDA.exe"; Tasks: desktopicon

[Run]
; 画面表示に必要な WebView2 が無ければ、静かにインストールする
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "{cm:InstallingWebView2}"; Check: WebView2Missing and WebView2Downloaded; Flags: waituntilterminated
; 通常インストール: 最後に「起動する」のチェックを出す
Filename: "{app}\OQIDA.exe"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent
; アプリ内アップデート（サイレント）: 終わったら自動で起動し直す
Filename: "{app}\OQIDA.exe"; Flags: nowait skipifnotsilent

[Code]
var
  WebView2Ready: Boolean;   { WebView2 のインストーラーをダウンロードできたか }

{ WebView2（画面表示に使う Edge の部品）が入っているかを、レジストリで調べる }
function WebView2Missing(): Boolean;
var
  ver: String;
begin
  Result := True;
  { 全ユーザー向け（64bit / 32bit）と、ユーザー単位の3か所を確認する }
  if RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', ver) and (ver <> '') and (ver <> '0.0.0.0') then
    Result := False
  else if RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', ver) and (ver <> '') and (ver <> '0.0.0.0') then
    Result := False
  else if RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', ver) and (ver <> '') and (ver <> '0.0.0.0') then
    Result := False;
end;

function WebView2Downloaded(): Boolean;
begin
  Result := WebView2Ready;
end;

{ 必要なときだけ、公式のブートストラップ版インストーラーを取得する }
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  WebView2Ready := False;
  if not WebView2Missing() then
    exit;
  try
    DownloadTemporaryFile('https://go.microsoft.com/fwlink/p/?LinkId=2124703',
      'MicrosoftEdgeWebview2Setup.exe', '', nil);
    WebView2Ready := True;
  except
    WebView2Ready := False;   { 取れなくても止めない。アプリ側が起動時にもう一度チェックする }
  end;
end;
