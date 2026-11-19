# foxbook-speech

Foxbook の Firefox 拡張へ、ローカル音声認識を共通機能として提供するための基盤です。Native Messaging Host は Firefox との入出力と許可済み拡張の入口だけを担当し、録音・変換・マイク排他・Whisper／ReazonSpeech の実行は単一のローカルサービスが担当します。

`foxbook_speech` Native Messaging adapter、Unix socket service、Whisper／ReazonSpeechの録音・認識とsystemd --user unitは実装済みです。Voice Editorの二Port移行と、両エンジンの実機録音・Firefox経由の動作を確認しています。Surfaceでの共有service測定などの残作業は[TODO](TODO.md)を参照してください。

複数アプリ向け音声アシスタントの共通UIは、独立構成要素として[表示試作](assistant-ui/README.md)を追加しています。試作は音声serviceへ接続せず、状態表示とドラッグ配置だけを確認します。

## 責務

- `foxbook_speech` Native Messaging Host の登録・要求検証・サービスへの中継
- ユーザー単位の音声サービス、Unix domain socket、systemd --user の運用
- マイク利用の排他、録音・変換・取消・タイムアウト・一時ファイルの回収
- 固定されたローカル設定による Whisper と ReazonSpeech の実行・Worker管理
- 共通音声API、導入手順、自動試験と実機試験

認識テキストの編集、履歴・定型文、音声コマンドの意味解釈、Focodex／OSK連携、端末制御やファイル操作は担当しません。

## 構成

```text
Firefox 拡張
  → connectNative("foxbook_speech")
  → 接続ごとの Native Messaging Host adapter
  → 所有者限定 Unix domain socket
  → 単一の foxbook-speech service
  → マイク / Whisper CLI / ReazonSpeech Worker
```

Native Messaging Host のコードと登録名は一つですが、Firefox は接続ごとにHostプロセスを起動します。そのためマイク状態とモデルをHost自身へ保持せず、serviceで一元管理します。

`native_host/foxbook_speech.py` はNative Messagingのバイナリフレームを検証してUnix socketへ中継します。HostをFirefoxへ登録するスクリプトは `scripts/install_host.py` です。serviceは`arecord`、`ffmpeg`と固定されたエンジン・モデルを使います。

## 初回導入

以下はTHE SESSION TOOLSの音声操作とVoice Editorの両方に必要なローカル環境です。各リポジトリは同じ親ディレクトリへ配置します。Linuxでは`arecord`（`alsa-utils`）、`ffmpeg`、C++ビルド用の`cmake`とコンパイラ、ReazonSpeechモデル取得用のGit LFSも必要です。Ubuntu/Debian系では次が一例です（他のディストリビューションでは対応するパッケージ名を使います）。

```bash
sudo apt install alsa-utils ffmpeg cmake build-essential git-lfs unzip
git lfs install
```

```bash
git clone https://github.com/tuyomori-cyber/foxbook-speech.git
git clone https://github.com/ggml-org/whisper.cpp.git
git clone https://huggingface.co/reazon-research/reazonspeech-k2-v2.git reazonspeech
```

ReazonSpeechモデルの取得にはGit LFSが必要です。`reazonspeech`でPython環境を作り、`sherpa-onnx`を導入します。

```bash
cd reazonspeech
python3 -m venv .venv
.venv/bin/pip install sherpa-onnx
```

Whisper.cppはCLIとbaseモデルを用意します。THE SESSION TOOLSの音声操作はReazonSpeechを使うが、共有serviceの導入条件としてWhisperの固定パスも満たします。

```bash
cd ../whisper.cpp
cmake -B build
cmake --build build --config Release
./models/download-ggml-model.sh base
```

次にこのリポジトリへ戻り、KWSモデル、Native Host、serviceを導入します。KWSモデルはGit管理しません。

```bash
cd ../foxbook-speech
mkdir -p models/kws
curl -fL -o /tmp/foxbook-kws-gigaspeech.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.tar.bz2
tar -xjf /tmp/foxbook-kws-gigaspeech.tar.bz2 -C models/kws
make -C native native-kws
```

`systemd/foxbook-speech.service.in` はユーザー単位の常駐service templateです。導入時は次を順に実行します。`--enable` はserviceを起動するため、実機の固定パスと依存ファイルを確認した後にだけ指定します。

```bash
python3 scripts/install_host.py
python3 scripts/install_service.py
python3 scripts/install_service.py --enable
```

### THE SESSION TOOLS音声操作の導入

メトロノーム音声操作の既定は「みらい」です。初回導入に加え、[「みらい」の導入](#みらいの導入とc比較診断)を完了してから、THE SESSION TOOLSを再読み込みします。`FOX`を明示的に選ぶ場合は、初回導入で配置したネイティブKWSとKWSモデルを使います。

```bash
make -C native native-kws
python3 scripts/install_host.py
systemctl --user restart foxbook-speech
```

Host登録はVoice EditorとTHE SESSION TOOLSの両方を許可する。The Sessionを開いた時、LEDが緑の「呼びかけを待機中」なら利用可能である。検出中はserviceがKWSを止めてマイクを解放し、3秒のReazonSpeech認識後に待機へ戻る。Voice Editorの手動録音は変更しない。必要なモデルや実行ファイルが不足するとLEDは赤になる。

service単体の実機録音は、Voice Editorを使わず次で確認できる。実行中は指定秒数だけ話し、最後の`result`イベントの`text`を確認する。`Ctrl+C`なら録音を取消する。

```bash
python3 scripts/diagnose_recording.py --seconds 5
```

## ウェイクワードの単独実験

`diagnose_wakeword.py`は共有serviceとは別の実験用コマンドです。英語KWSモデルで`FOX`または`HEY FOX`の検出だけを試し、録音・認識の開始やFirefoxへの通知は行いません。マイク音声を保存しません。THE SESSION TOOLSの実運用ではserviceがKWSと録音の引継ぎを管理しますが、この診断を実行中は他の音声録音を同時に使わないでください。

### 「みらい」の導入とC++比較診断

「みらい」は[onnx-wakeword](https://github.com/voicute/onnx-wakeword)の日本語モデルを使う実験的なウェイクワードです。通常の初回導入を済ませた後、次の手順で依存物を固定パスへ用意します。共有serviceは`foxbook-speech`と同じ親ディレクトリの`foxbook-mirai-test`を参照します。このディレクトリはGit管理しません。

```bash
cd ~/project
mkdir -p foxbook-mirai-test
git clone https://github.com/voicute/onnx-wakeword.git foxbook-mirai-test/onnx-wakeword
python3 -m venv foxbook-mirai-test/.venv
foxbook-mirai-test/.venv/bin/pip install --upgrade pip
foxbook-mirai-test/.venv/bin/pip install onnx-wakeword
```

`onnx-wakeword`パッケージはPython比較試験とONNX Runtime共有ライブラリを提供し、cloneしたリポジトリは`melspectrogram.onnx`、`models/ja/mirai_r1.onnx`、`models/ja/model_info.json`を提供します。導入後は、モデルの存在を確認します。

```bash
MIRAI_ROOT="$HOME/project/foxbook-mirai-test"
test -r "$MIRAI_ROOT/onnx-wakeword/models/melspectrogram.onnx"
test -r "$MIRAI_ROOT/onnx-wakeword/models/ja/mirai_r1.onnx"
test -r "$MIRAI_ROOT/onnx-wakeword/models/ja/model_info.json"
```

ビルドにはONNX Runtime公式C APIヘッダーが必要です。Python wheelにはヘッダーが同梱されないため、同じ版の公式NuGet配布物`Microsoft.ML.OnnxRuntime`からヘッダー一式だけを取り出します。GitHubへの直接接続を必要としません。実行時には上記仮想環境のONNX Runtime共有ライブラリを動的に読み込むため、共有serviceのPython環境へONNX Runtimeを追加する必要はありません。

```bash
MIRAI_ROOT="$HOME/project/foxbook-mirai-test"
ORT_VERSION=$("$MIRAI_ROOT/.venv/bin/python" -c 'import onnxruntime; print(onnxruntime.__version__)')
ORT_NUGET=$(mktemp /tmp/Microsoft.ML.OnnxRuntime.XXXXXX.nupkg)
ORT_STAGE=$(mktemp -d /tmp/foxbook-onnxruntime-include.XXXXXX)
curl -fL "https://www.nuget.org/api/v2/package/Microsoft.ML.OnnxRuntime/$ORT_VERSION" -o "$ORT_NUGET"
unzip -oq "$ORT_NUGET" 'build/native/include/*' -d "$ORT_STAGE"
mkdir -p /tmp/foxbook-onnxruntime-include
cp "$ORT_STAGE/build/native/include/"*.h /tmp/foxbook-onnxruntime-include/
make -C "$HOME/project/foxbook-speech/native" mirai-kws
```

次はどのカレントディレクトリからでも実行できます。音声は保存せず、10秒ごとに診断プロセス自身のCPU使用率とRSSを表示します（`arecord`の負荷は含みません）。終了は`Ctrl+C`です。これは共有serviceを起動しない単独診断なので、THE SESSION TOOLSのタブとVoice Editor、他のマイク診断を終了してから実行します。Python版の`mic_test.py`と同じモデル、閾値0.5、L1連続2回（最大2フレームの間隔を許容）、L3待機1.5秒を使います。入力は`arecord`の既定デバイスの16kHzモノラルであり、Python版のPortAudio入力とはデバイスや音声経路が異なる場合があります。

```bash
MIRAI_ROOT="$HOME/project/foxbook-mirai-test"
SPEECH_ROOT="$HOME/project/foxbook-speech"
ORT_LIB=$("$MIRAI_ROOT/.venv/bin/python" -c 'import pathlib, onnxruntime; p=pathlib.Path(onnxruntime.__file__).parent / "capi"; print(next(p.glob("libonnxruntime.so.*")))')
"$SPEECH_ROOT/build/native/mirai_kws" --runtime "$ORT_LIB" \
  --mel "$MIRAI_ROOT/onnx-wakeword/models/melspectrogram.onnx" \
  --model "$MIRAI_ROOT/onnx-wakeword/models/ja/mirai_r1.onnx"
```

比較時は同じマイク・距離・声量で発話回数と検出回数、無発話時の誤検出を記録します。Python版の`mic_test.py --info models/ja/model_info.json`のCPU/RSSは別端末から`ps -C python -o pid,pcpu,rss,args`で確認できます（CPUは起動以来の平均）。C++版は区間CPUなので比較時は測定範囲の違いに注意してください。C++版の`--raw FILE`では16kHzモノラルS16_LEの生PCMを読み、各窓のスコアを出力できます。

#### THE SESSION TOOLSでの実験

上記の導入、ビルド、単独診断が終わってから、動作中の録音を終了し、ユーザーserviceを再起動します。「みらい」が既定ですが、以前`FOXBOOK_WAKEWORD=fox`を指定した場合は以下で解除します。必要な実行ファイル、仮想環境の`libonnxruntime.so.*`、モデルが欠けると待機LEDは赤になります。

```bash
systemctl --user unset-environment FOXBOOK_WAKEWORD
systemctl --user restart foxbook-speech
```

THE SESSION TOOLS拡張とThe Sessionタブを再読み込みし、待機中に「みらい」、続いてコマンドを話します。チューナー中も「みらい」単独で終了する実装です。dynabookのFirefoxで発話検出、非アクティブ時の一時停止・復帰、タブ終了時のマイク解放を確認しました。コマンド全種とチューナーの動作、Surfaceは引き続き確認します。FOXへ切り替えるには次を実行してからタブを再読み込みします。この設定はsystemdユーザーマネージャーの環境に保存され、ログアウト等で初期化される場合があります。

```bash
systemctl --user set-environment FOXBOOK_WAKEWORD=fox
systemctl --user restart foxbook-speech
```

「みらい」に戻す場合は`systemctl --user unset-environment FOXBOOK_WAKEWORD`の後にserviceを再起動し、タブを再読み込みします。service unitやdrop-inに`FOXBOOK_WAKEWORD`を設定している場合はそちらが適用されるため、その設定も確認してください。

ReazonSpeech用環境の`../reazonspeech/.venv/bin/python`と`sherpa-onnx`、`arecord`、次のモデルが必要です。公式配布モデルのREADMEにはApache License 2.0と記載されています。ファイルはGit管理しません。

```bash
mkdir -p models/kws
curl -fL -o /tmp/foxbook-kws-gigaspeech.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.tar.bz2
tar -xjf /tmp/foxbook-kws-gigaspeech.tar.bz2 -C models/kws
```

```bash
python3 scripts/diagnose_wakeword.py --word fox
# Ctrl+Cで終了してから、もう一方を試す
python3 scripts/diagnose_wakeword.py --word hey-fox
```

入力は`arecord`の既定デバイスを使い、左チャンネルをリアルタイムで検出器へ渡します。別のALSA入力は`--device`で指定できます。比較用に`--backend alsa`と`--backend portaudio`も残しています。検出閾値は`--threshold`で変更できます（既定0.25）。英語モデルのため、日本語話者の発音での検出率・誤検出率とSurface上の負荷は未測定です。

検出しない場合は`--show-level`を付けると、音声を保存せず入力のピークを2秒ごとに表示できます。話すと値が上がるか確認してください。Python版も既定で10秒ごとに区間CPU使用率とプロセス自身のRSSを表示します。`--report-every 0`で止められます。

### C++ネイティブ版の比較診断

Pythonラッパーの常駐コストを含めない比較用に、同じ`sherpa-onnx`配布物の安定C ABIへC++から直接つなぐ診断アプリを用意しています。Python版と同じ英語KWSモデル、`FOX`、既定ALSA入力の左チャンネル、閾値`0.25`、推論スレッド1本を使います。サービスやFirefoxへは接続せず、音声も保存しません。

`sherpa-onnx`を入れた既存の`../reazonspeech/.venv`を使う場合は、次でビルドして実行します。起動後は10秒ごとに、その区間のCPU使用率とプロセス自身のRSSを表示します。`--show-level`はPython版と同じく2秒ごとの入力ピークを表示します。`Ctrl+C`で終了してください。

```bash
make -C native native-kws
build/native/wakeword_kws --model-dir models/kws/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01
```

USBマイクのデバイスを明示する場合は`--device`を指定します。入力ピークも同時に確認するなら`--show-level`を加えます。別のPython環境を使う場合は、ビルド時に`sherpa_onnx`パッケージへのパスを渡します。

```bash
make -C native native-kws SHERPA_ONNX_PREFIX=/path/to/site-packages/sherpa_onnx
build/native/wakeword_kws --model-dir models/kws/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01 --device default --show-level
```

## 状態

- 文書の正本: [仕様書 v0.1](specification/foxbook-speech仕様書v0.1.md)
- Foxbook全体の設計: [Foxbook 全体アーキテクチャ](../foxbook/docs/Foxbook_全体アーキテクチャ_2026-11-16.md)
- 実装・検証の保留事項: [TODO](TODO.md)
- Voice Editorとの現行契約: [IF-VE-SP-001](../foxbook/docs/interfaces/fox-voice-editor--foxbook-speech.md)

## 初期の利用方針

初期版では利用者の明示操作で録音を開始し、同時要求は待ち行列に入れず `BUSY` で拒否します。ブラウザから任意コマンド、モデル／実行ファイル／音声ファイルのパス、音声バイト列は受け取りません。

Whisper は認識要求ごとにCLIを起動します。ReazonSpeech K2はservice全体で一つのWorkerを再利用し、最後の利用から5分で解放します。録音は最大30秒で、自動停止して認識へ進みます。モデルの配置はservice側で固定しています。端末固有のマイク補正は共有serviceでは未実装で、設定方式も未決定です。実機診断では `--engine reazonspeech_k2` を指定します。
