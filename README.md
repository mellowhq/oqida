# OQIDA

YouTubeのURLを貼って、MP4かMP3で保存する個人用ソフト。
中身は yt-dlp。ダーク/ライト/システム、日本語/English の切り替え、アプリ内アップデートつき。

## フォルダの中身

| 場所 | 役割 |
|---|---|
| `main.py` | アプリの入口。画面とプログラムをつなぐ |
| `ui/` | 見た目（HTML・CSS・JS）。文言は `ui/i18n.js` |
| `core/` | ダウンロード・更新の処理 |
| `installer/oqida.iss` | インストーラーの設計図（デスクトップショートカットもここ） |
| `.github/workflows/release.yml` | タグを打つと自動でインストーラーを作る設定 |
| `build.bat` | 自分のPCでインストーラーを作りたいとき用 |

## 最初にやること（1回だけ）

1. `core/version.py` の `UPDATE_REPO` を、自分のGitHubのリポジトリ名にする（例 `mellowhq/oqida`）。
   アプリはここのReleasesを見て新しい版を探す。**公開(Public)リポジトリにしてね**（非公開だとアプリから見えない）。
2. このフォルダをそのリポジトリにアップロード（push）する。

## インストーラーを作る（GitHubにおまかせ）

1. GitHubで `v0.1.0` のようなタグを付けてpushする。
   ```
   git tag v0.1.0
   git push origin v0.1.0
   ```
2. 数分待つと、リポジトリの Releases に `OQIDA-0.1.0-Setup.exe` が出る。
3. それをダウンロードして実行すると、インストールされてデスクトップにショートカットができる。

自分のPCで作りたい場合は、Python 3.12 と Inno Setup 6 を入れて `build.bat` をダブルクリック。

## アップデートの出し方

1. 直したあと、次の番号のタグを付けてpushする（例 `v0.2.0`）。
2. Releasesに新しいインストーラーが出る。
3. 手元のOQIDAで **設定 → アップデート → 更新を確認 → ダウンロード → 更新して再起動**。
   （起動時に自動で確認もする。バナーも出る）

yt-dlp（YouTubeを読む部分）はアプリとは別に更新される。
**設定 → アップデート** の「yt-dlpを自動で更新」がオンなら、起動のたびに最新へ入れ替える。
YouTube側の変更で急に落とせなくなったら、まずここの「更新を確認」を押す。

## 初回起動

最初の1回だけ、yt-dlp・ffmpeg・Deno（YouTube対応に必要）を自動で取得する（約250MB）。
保存先は `%LOCALAPPDATA%\OQIDA`（設定の「データフォルダ」から開ける）。

## 注意

- 署名なしのexeなので、初回は Windows の SmartScreen が「PCを保護しました」と出ることがある。
  「詳細情報」→「実行」で進める。
- 動画の保存は、自分で見る個人利用の範囲で。著作権や YouTube の利用規約は自分で気をつけて。
- 画面の確認だけなら、ブラウザで `ui/index.html?mock=1` を開くと動作サンプルが出る。

## 開発メモ

```
pip install -r requirements.txt
python main.py          # 起動（Windows）
python -m pytest tests  # テスト（ffmpegとyt-dlpが入っていること）
```
