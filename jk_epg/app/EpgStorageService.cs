// Derived from nanamitm/jkcnsl-cache (MIT), EPG-only extraction.
using Microsoft.Data.Sqlite;

namespace jkcnsl_cache;

public sealed class EpgStorageService : BackgroundService
{
    private readonly ILogger<EpgStorageService> _logger;
    private readonly string _dbPath;
    private readonly int _retentionDays;

    public EpgStorageService(IConfiguration config, ILogger<EpgStorageService> logger)
    {
        _logger = logger;
        _dbPath = config["EpgStorage:DbPath"] ?? "local/epg.db";
        _retentionDays = Math.Max(1, config.GetValue("EpgStorage:RetentionDays", 60));
    }

    public void SavePrograms(string channel, IReadOnlyList<EpgProgram> programs)
    {
        if (programs.Count == 0) return;
        try
        {
            using var conn = OpenConnection();
            using var tx = conn.BeginTransaction();
            using var cmd = conn.CreateCommand();
            cmd.CommandText =
                "INSERT OR REPLACE INTO epg_programs (channel, title, start_at, end_at, source, genre_code, genre_name) " +
                "VALUES ($ch, $title, $start, $end, $source, $genre_code, $genre_name)";
            var pCh        = cmd.Parameters.Add("$ch",         SqliteType.Text);
            var pTitle     = cmd.Parameters.Add("$title",      SqliteType.Text);
            var pStart     = cmd.Parameters.Add("$start",      SqliteType.Integer);
            var pEnd       = cmd.Parameters.Add("$end",        SqliteType.Integer);
            var pSource    = cmd.Parameters.Add("$source",     SqliteType.Text);
            var pGenreCode = cmd.Parameters.Add("$genre_code", SqliteType.Text);
            var pGenreName = cmd.Parameters.Add("$genre_name", SqliteType.Text);

            pCh.Value = channel;
            foreach (var p in programs)
            {
                pTitle.Value     = p.Title;
                pStart.Value     = p.StartAt.ToUnixTimeSeconds();
                pEnd.Value       = p.EndAt.ToUnixTimeSeconds();
                pSource.Value    = p.Source;
                pGenreCode.Value = (object?)p.GenreCode ?? DBNull.Value;
                pGenreName.Value = (object?)p.GenreName ?? DBNull.Value;
                cmd.ExecuteNonQuery();
            }
            tx.Commit();
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "[EpgStorage] EPGデータの保存に失敗しました: channel={Channel}", channel);
        }
    }

    public void ReplaceImportedPrograms(string channel, IReadOnlyList<EpgProgram> programs)
    {
        if (programs.Count == 0) return;

        try
        {
            using var conn = OpenConnection();
            using var tx = conn.BeginTransaction();

            var rangeStart = programs.Min(p => p.StartAt).ToUnixTimeSeconds();
            var rangeEnd = programs.Max(p => p.EndAt).ToUnixTimeSeconds();

            using (var delete = conn.CreateCommand())
            {
                delete.CommandText =
                    "DELETE FROM epg_import_programs " +
                    "WHERE channel = $ch AND end_at > $from AND start_at < $to";
                delete.Parameters.AddWithValue("$ch", channel);
                delete.Parameters.AddWithValue("$from", rangeStart);
                delete.Parameters.AddWithValue("$to", rangeEnd);
                delete.ExecuteNonQuery();
            }

            using var insert = conn.CreateCommand();
            insert.CommandText =
                "INSERT OR REPLACE INTO epg_import_programs (channel, title, start_at, end_at, source, genre_code, genre_name) " +
                "VALUES ($ch, $title, $start, $end, $source, $genre_code, $genre_name)";
            var pCh = insert.Parameters.Add("$ch", SqliteType.Text);
            var pTitle = insert.Parameters.Add("$title", SqliteType.Text);
            var pStart = insert.Parameters.Add("$start", SqliteType.Integer);
            var pEnd = insert.Parameters.Add("$end", SqliteType.Integer);
            var pSource = insert.Parameters.Add("$source", SqliteType.Text);
            var pGenreCode = insert.Parameters.Add("$genre_code", SqliteType.Text);
            var pGenreName = insert.Parameters.Add("$genre_name", SqliteType.Text);

            pCh.Value = channel;
            foreach (var p in programs)
            {
                pTitle.Value = p.Title;
                pStart.Value = p.StartAt.ToUnixTimeSeconds();
                pEnd.Value = p.EndAt.ToUnixTimeSeconds();
                pSource.Value = p.Source;
                pGenreCode.Value = (object?)p.GenreCode ?? DBNull.Value;
                pGenreName.Value = (object?)p.GenreName ?? DBNull.Value;
                insert.ExecuteNonQuery();
            }

            tx.Commit();
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "[EpgStorage] インポートEPGデータの保存に失敗しました: channel={Channel}", channel);
        }
    }

    public (DateTimeOffset? Earliest, DateTimeOffset? Latest) GetDateRange()
    {
        if (!File.Exists(_dbPath)) return (null, null);
        try
        {
            using var conn = OpenConnection(readOnly: true);
            using var cmd = conn.CreateCommand();
            cmd.CommandText = "SELECT MIN(start_at), MAX(start_at) FROM epg_programs";
            using var reader = cmd.ExecuteReader();
            if (!reader.Read() || reader.IsDBNull(0)) return (null, null);
            return (
                DateTimeOffset.FromUnixTimeSeconds(reader.GetInt64(0)),
                DateTimeOffset.FromUnixTimeSeconds(reader.GetInt64(1))
            );
        }
        catch { return (null, null); }
    }

    public Dictionary<string, List<EpgProgram>> QueryPrograms(DateTimeOffset from, DateTimeOffset to)
    {
        var result = new Dictionary<string, List<EpgProgram>>(StringComparer.Ordinal);
        if (!File.Exists(_dbPath)) return result;

        try
        {
            using var conn = OpenConnection(readOnly: true);
            using var cmd = conn.CreateCommand();
            cmd.CommandText =
                "SELECT channel, title, start_at, end_at, source, genre_code, genre_name " +
                "FROM epg_programs WHERE end_at > $from AND start_at < $to " +
                "ORDER BY channel, start_at";
            cmd.Parameters.AddWithValue("$from", from.ToUnixTimeSeconds());
            cmd.Parameters.AddWithValue("$to",   to.ToUnixTimeSeconds());

            using var reader = cmd.ExecuteReader();
            while (reader.Read())
            {
                var channel   = reader.GetString(0);
                var title     = reader.GetString(1);
                var startAt   = DateTimeOffset.FromUnixTimeSeconds(reader.GetInt64(2));
                var endAt     = DateTimeOffset.FromUnixTimeSeconds(reader.GetInt64(3));
                var source    = reader.GetString(4);
                var genreCode = reader.IsDBNull(5) ? null : reader.GetString(5);
                var genreName = reader.IsDBNull(6) ? null : reader.GetString(6);

                if (!result.TryGetValue(channel, out var list))
                    result[channel] = list = new List<EpgProgram>();
                list.Add(new EpgProgram(title, startAt, endAt, source, genreCode, genreName));
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "[EpgStorage] EPGデータの取得に失敗しました");
        }

        return result;
    }

    public Dictionary<string, List<EpgProgram>> QueryImportedPrograms(DateTimeOffset from, DateTimeOffset to)
    {
        return QueryProgramsCore("epg_import_programs", from, to);
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var dir = Path.GetDirectoryName(Path.GetFullPath(_dbPath));
        if (!string.IsNullOrEmpty(dir))
            Directory.CreateDirectory(dir);

        using (var conn = OpenConnection())
        {
            InitSchema(conn);
            CleanupOld(conn);
        }

        while (!stoppingToken.IsCancellationRequested)
        {
            try { await Task.Delay(TimeSpan.FromHours(1), stoppingToken); }
            catch (OperationCanceledException) { break; }
            try
            {
                using var conn = OpenConnection();
                CleanupOld(conn);
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "[EpgStorage] EPGクリーンアップに失敗しました");
            }
        }
    }

    private void CleanupOld(SqliteConnection conn)
    {
        var cutoff = DateTimeOffset.UtcNow.AddDays(-_retentionDays).ToUnixTimeSeconds();
        using var cmd = conn.CreateCommand();
        cmd.CommandText = "DELETE FROM epg_programs WHERE end_at < $cutoff";
        cmd.Parameters.AddWithValue("$cutoff", cutoff);
        var deleted = cmd.ExecuteNonQuery();
        if (deleted > 0)
            _logger.LogInformation("[EpgStorage] 古いEPGを削除しました count={Count}", deleted);
    }

    private SqliteConnection OpenConnection(bool readOnly = false)
    {
        var cs = new SqliteConnectionStringBuilder
        {
            DataSource = _dbPath,
            Mode = readOnly ? SqliteOpenMode.ReadOnly : SqliteOpenMode.ReadWriteCreate,
        }.ToString();
        var conn = new SqliteConnection(cs);
        conn.Open();
        if (!readOnly)
        {
            using var cmd = conn.CreateCommand();
            cmd.CommandText = "PRAGMA journal_mode=WAL";
            cmd.ExecuteNonQuery();
            cmd.CommandText = "PRAGMA synchronous=NORMAL";
            cmd.ExecuteNonQuery();
        }
        return conn;
    }

    private static void InitSchema(SqliteConnection conn)
    {
        using var cmd = conn.CreateCommand();
        cmd.CommandText = """
            CREATE TABLE IF NOT EXISTS epg_programs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                channel    TEXT    NOT NULL,
                title      TEXT    NOT NULL,
                start_at   INTEGER NOT NULL,
                end_at     INTEGER NOT NULL,
                source     TEXT    NOT NULL,
                genre_code TEXT,
                genre_name TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_epg_channel_start ON epg_programs(channel, start_at);
            CREATE INDEX IF NOT EXISTS idx_epg_end ON epg_programs(end_at);

            CREATE TABLE IF NOT EXISTS epg_import_programs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                channel    TEXT    NOT NULL,
                title      TEXT    NOT NULL,
                start_at   INTEGER NOT NULL,
                end_at     INTEGER NOT NULL,
                source     TEXT    NOT NULL,
                genre_code TEXT,
                genre_name TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_epg_import_channel_start ON epg_import_programs(channel, start_at);
            CREATE INDEX IF NOT EXISTS idx_epg_import_end ON epg_import_programs(end_at);
            """;
        cmd.ExecuteNonQuery();
    }

    private Dictionary<string, List<EpgProgram>> QueryProgramsCore(string tableName, DateTimeOffset from, DateTimeOffset to)
    {
        var result = new Dictionary<string, List<EpgProgram>>(StringComparer.Ordinal);
        if (!File.Exists(_dbPath)) return result;

        try
        {
            using var conn = OpenConnection(readOnly: true);
            using var cmd = conn.CreateCommand();
            cmd.CommandText =
                $"SELECT channel, title, start_at, end_at, source, genre_code, genre_name " +
                $"FROM {tableName} WHERE end_at > $from AND start_at < $to " +
                $"ORDER BY channel, start_at";
            cmd.Parameters.AddWithValue("$from", from.ToUnixTimeSeconds());
            cmd.Parameters.AddWithValue("$to", to.ToUnixTimeSeconds());

            using var reader = cmd.ExecuteReader();
            while (reader.Read())
            {
                var channel = reader.GetString(0);
                var title = reader.GetString(1);
                var startAt = DateTimeOffset.FromUnixTimeSeconds(reader.GetInt64(2));
                var endAt = DateTimeOffset.FromUnixTimeSeconds(reader.GetInt64(3));
                var source = reader.GetString(4);
                var genreCode = reader.IsDBNull(5) ? null : reader.GetString(5);
                var genreName = reader.IsDBNull(6) ? null : reader.GetString(6);

                if (!result.TryGetValue(channel, out var list))
                    result[channel] = list = new List<EpgProgram>();
                list.Add(new EpgProgram(title, startAt, endAt, source, genreCode, genreName));
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "[EpgStorage] EPGデータの取得に失敗しました: table={Table}", tableName);
        }

        return result;
    }
}
