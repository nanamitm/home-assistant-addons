# JK EPG

日本の地上波・BS・CS番組表を取得し、Home Assistantのサイドバーから表示します。

## 設定

- `timezone`: 放送時刻のタイムゾーン。通常は `Asia/Tokyo` のまま使用します。
- `update_interval`: 番組表を再取得する間隔（秒）。外部サービスへの負荷を避けるため、3600秒未満にはできません。
- `retention_days`: SQLiteに保存する番組表の日数。
- `nhk_area`: NHK番組APIの地域コード。東京は `130` です。
- `nhk_api_key`: NHK番組APIから発行されたAPIキー。空の場合、NHK固有チャンネルの一部は取得されません。
- `enable_atx`, `enable_ouj`, `enable_subchannels`: 各補助取得元の有効・無効。
- `install_ha_integration`: 番組センサーと番組表カレンダーを提供するカスタム統合をHome Assistantへ配置します。

データベースはアドオンの永続領域 `/data/epg.db` に保存され、通常のHome Assistantバックアップ対象になります。

## データ取得について

TVerのWeb向けAPIおよび一部放送局のWebページを利用するため、提供元の仕様変更によって取得できなくなることがあります。取得失敗時は保存済みデータを表示し、設定された間隔で再試行します。

「取得状態」では、取得元ごとの最終試行・取得件数・応答時間・連続失敗を確認できます。取得結果が0件になった場合や期待した形式でなかった場合は「異常」と表示されるため、外部APIの仕様変更を切り分けられます。

SQLiteキャッシュは起動時に整合性を検査します。破損を検出すると `/data/epg.db.corrupt-日時` へ退避し、新しいキャッシュを自動作成します。復旧が発生した時刻は取得状態に表示されます。

NHK番組APIを有効にした場合は、同APIの利用規約に従ってください。画面には「NHK番組の情報提供: NHK」を表示します。

## Home Assistant連携

1. `install_ha_integration` を有効にしてアドオンを起動します。
2. Home Assistantを再起動します。
3. 「設定」→「デバイスとサービス」→「統合を追加」から `JK EPG` を追加します。
4. URLは通常、初期値の `http://1815012f-jk-epg:8099` のまま使用できます。

統合を追加すると、チャンネルごとに現在の番組を状態、次の番組や開始・終了時刻を属性に持つセンサーと、全チャンネルの番組を含む読み取り専用カレンダーが作成されます。

番組開始前の通知は、Home AssistantのオートメーションでJK EPGのカレンダーをトリガーに指定します。例えば開始10分前に通知する場合は、カレンダートリガーのオフセットを `-00:10:00` に設定し、アクションで使用する通知サービスを選択してください。番組名は `trigger.calendar_event.summary`、チャンネル名は `trigger.calendar_event.location` から参照できます。

## API

- `GET api/health`
- `GET api/programs/current`
- `GET api/programs/schedule?date=YYYY-MM-DD`
- `GET api/programs/schedule/range`
- `GET api/programs/status`
- `POST api/programs/refresh`

Ingress以外からAPIを利用する場合は、ネットワーク設定で8099/tcpを公開してください。
