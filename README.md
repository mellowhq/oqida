# OQIDA

動画のURLを貼って、MP4またはMP3で保存するWindows用デスクトップソフト。YouTube、X（Twitter）、TikTok、Instagram、ニコニコ動画など、yt-dlp が対応するサイトで使えます。
対応サイト一覧は[こちら](supportedsites.md)
内部で [yt-dlp](https://github.com/yt-dlp/yt-dlp) と [FFmpeg](https://ffmpeg.org/) を使用しています。

A Windows desktop app that saves a video URL as MP4 or MP3. Works with YouTube, X (Twitter), TikTok, Instagram and other sites supported by yt-dlp.

## 機能

- URLを貼って MP4 / MP3 を選ぶだけで保存（画質・音質の指定、複数のキュー対応、サムネイル表示）
- YouTube 以外にも、X（Twitter）・TikTok など多数のサイトに対応
- GIF への変換（開始位置・長さ・幅・コマ数を指定。指定した区間だけを取得して変換するので、長い動画でも速い）
- ダウンロード履歴（アプリを閉じても一覧が残り、同じURLは重複を警告）
- 失敗したときの詳細ログ表示とコピー（原因の共有に使える／ユーザー名のフォルダは伏せる）
- 一時停止・再開、速度制限
- MP4・MP3 などの区間指定（指定した区間だけ保存）
- 音声形式は MP3 / M4A / Opus / FLAC / WAV に対応、サムネイル画像の保存も可能
- yt-dlp の更新が壊れていたとき、設定から旧バージョンに戻せる
- ファイルサイズの上限を指定でき、MP4・MP3・GIF を上限内に収まるよう自動で調整（上限に収まらないときはエラーで通知）
- GIF の範囲は「開始・終了・長さ」のどれを変えても連動
- パソコン内の動画/音声を別の形式に変換（MP4・MP3・M4A・Opus・FLAC・WAV。区間指定・サイズ上限つき）
- パソコン内の動画ファイルを GIF に変換（区間のオンオフを選べ、オフなら動画まるごと）（左メニューの「GIF変換」。元のファイルと同じフォルダに保存）
- テーマ切り替え（ダーク / ライト / システム）とアクセントカラーの変更
- 表示言語の切り替え（日本語 / English）
- アプリ内アップデート（起動時に新しい版があれば確認ダイアログを表示。設定 → アップデートからも可能）
- yt-dlp の自動更新
- デスクトップショートカット付きインストーラー

## インストール

[Releases](https://github.com/mellowhq/oqida/releases) から最新の `OQIDA-x.y.z-Setup.exe` をダウンロードして実行します。
管理者権限は不要です。

初回起動時のみ、yt-dlp・FFmpeg・Deno（YouTube対応に使用）を自動でダウンロードします（約250MB）。
画面表示には Microsoft Edge WebView2 ランタイムが必要です（最近の Windows には標準で入っています。無い場合はインストーラーが自動で導入します）。
署名のない実行ファイルのため、初回は Windows SmartScreen の警告が表示されることがあります。

## 使い方

1. URLを入力欄に貼り付ける
2. 形式（MP4 / MP3 / GIF）と画質・音質を選ぶ（GIF は開始・長さ・幅・コマ数を指定）
3. 「ダウンロード」を押す

保存先やテーマ、言語、アップデートは「設定」から変更できます。
サイト側の仕様変更で保存できなくなった場合は、設定の「yt-dlp」から更新してください。
ログインが必要な投稿や、ボット確認が出る場合は、設定の「ブラウザのCookie」でログイン済みのブラウザを選ぶと保存できることがあります。

## 開発

必要なもの: Python 3.12 / Windows 10 以降（WebView2）

```
pip install -r requirements.txt
python main.py
```

テスト（FFmpeg と yt-dlp が PATH にあること）:

```
pip install pytest pillow playwright
python -m pytest tests
```

画面の確認のみなら、ブラウザで `ui/index.html?mock=1` を開くと、ダミーデータで表示できます。

### ビルド

```
build.bat
```

Python 3.12 と [Inno Setup 6](https://jrsoftware.org/isinfo.php) が必要です。`dist/` にインストーラーが作られます。

### リリース

`v0.1.0` の形式のタグを push すると、GitHub Actions がインストーラーをビルドして Releases に添付します。
アプリは `core/version.py` の `UPDATE_REPO` にある Releases を参照してアップデートを検出します。

## 構成

| パス | 内容 |
|---|---|
| `main.py` | エントリーポイント（ウィンドウと画面側 API） |
| `core/` | ダウンロード処理・アップデート・設定 |
| `ui/` | 画面（HTML / CSS / JS）、文言は `ui/i18n.js` |
| `installer/oqida.iss` | Inno Setup のインストーラー定義 |
| `.github/workflows/release.yml` | リリースビルド |

## 注意

個人利用の範囲でお使いください。ダウンロードするコンテンツの著作権および各サービスの利用規約については、利用者の責任で確認してください。

## ライセンス・クレジット

yt-dlp（Unlicense）、FFmpeg（GPL ビルドを使用）、Deno（MIT）は、それぞれのライセンスに従って初回起動時に取得されます。
