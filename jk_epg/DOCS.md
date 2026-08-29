# JK EPG

日本の地上波・BS・CS番組表を取得し、Home Assistantのサイドバーから表示します。

## 設定

- `timezone`: 放送時刻のタイムゾーン。通常は `Asia/Tokyo` のまま使用します。
- `update_interval`: 番組表を再取得する間隔（秒）。外部サービスへの負荷を避けるため、3600秒未満にはできません。
- `retention_days`: SQLiteに保存する番組表の日数。
- `nhk_area`: NHK番組APIの地域コード。東京は `130` です。
- `nhk_api_key`: NHK番組APIから発行されたAPIキー。空の場合、NHK固有チャンネルの一部は取得されません。
- `enable_atx`, `enable_ouj`, `enable_subchannels`: 各補助取得元の有効・無効。

データベースはアドオンの永続領域 `/data/epg.db` に保存され、通常のHome Assistantバックアップ対象になります。

## データ取得について

TVerのWeb向けAPIおよび一部放送局のWebページを利用するため、提供元の仕様変更によって取得できなくなることがあります。取得失敗時は保存済みデータを表示し、設定された間隔で再試行します。

NHK番組APIを有効にした場合は、同APIの利用規約に従ってください。画面には「NHK番組の情報提供: NHK」を表示します。

## API

- `GET api/health`
- `GET api/programs/current`
- `GET api/programs/schedule?date=YYYY-MM-DD`
- `GET api/programs/schedule/range`

Ingress以外からAPIを利用する場合は、ネットワーク設定で8099/tcpを公開してください。
