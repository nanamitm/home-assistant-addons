// Derived from nanamitm/jkcnsl-cache (MIT), EPG-only extraction.
// See ../LICENSE and https://github.com/nanamitm/jkcnsl-cache.
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Net;
using System.Web;
using System.Xml.Linq;
using jkcnsl_cache.Sources;

namespace jkcnsl_cache;

public sealed class ProgramInfoService : BackgroundService
{
    private readonly IConfiguration _config;
    private readonly ILogger<ProgramInfoService> _logger;
    private readonly ChannelsStreamBroadcaster _broadcaster;
    private readonly ChannelCatalog _channelCatalog;
    private readonly EpgStorageService _epgStorage;
    private readonly EpgSourceRegistry _sources;
    private readonly EpgSourceMonitor _sourceMonitor;
    private readonly HttpClient _http;
    private readonly TimeZoneInfo _timeZone;
    private readonly string _nhkArea;
    private readonly object _lock = new();
    private readonly Dictionary<string, ProgramInfo> _currentPrograms = new();
    private readonly Dictionary<string, List<EpgProgram>> _epgPrograms = new();
    private readonly HashSet<DateOnly> _loadedBroadcastDates = new();
    private readonly SemaphoreSlim _refreshLock = new(1, 1);
    private DateOnly? _loadedNhkBroadcastDate;
    private DateOnly? _loadedAtxBroadcastDate;
    private DateOnly? _loadedOujBroadcastDate;
    private DateOnly? _loadedBs4SubChannelBroadcastDate;
    private DateOnly? _loadedBsTbsSubChannelBroadcastDate;
    private DateOnly? _loadedBsFujiSubChannelBroadcastDate;
    private DateTimeOffset _lastFetchUtc = DateTimeOffset.MinValue;
    private DateTimeOffset _lastImportUtc = DateTimeOffset.MinValue;
    private DateTimeOffset _lastRefreshFailureUtc = DateTimeOffset.MinValue;
    private DateTimeOffset _lastNhkFetchUtc = DateTimeOffset.MinValue;
    private DateTimeOffset _lastNhkAttemptUtc = DateTimeOffset.MinValue;
    private DateTimeOffset _lastAtxFetchUtc = DateTimeOffset.MinValue;
    private DateTimeOffset _lastAtxAttemptUtc = DateTimeOffset.MinValue;
    private DateTimeOffset _lastOujFetchUtc = DateTimeOffset.MinValue;
    private DateTimeOffset _lastOujAttemptUtc = DateTimeOffset.MinValue;
    private DateTimeOffset _lastBs4SubChannelFetchUtc = DateTimeOffset.MinValue;
    private DateTimeOffset _lastBs4SubChannelAttemptUtc = DateTimeOffset.MinValue;
    private DateTimeOffset _lastBsTbsSubChannelFetchUtc = DateTimeOffset.MinValue;
    private DateTimeOffset _lastBsTbsSubChannelAttemptUtc = DateTimeOffset.MinValue;
    private DateTimeOffset _lastBsFujiSubChannelFetchUtc = DateTimeOffset.MinValue;
    private DateTimeOffset _lastBsFujiSubChannelAttemptUtc = DateTimeOffset.MinValue;
    private bool _hasBroadcastSnapshot;

    private static readonly IReadOnlyDictionary<string, TVerBroadcasterInfo> JikkyoToTVer = new Dictionary<string, TVerBroadcasterInfo>
    {
        ["jk1"] = new("ota", 23, 120),
        ["jk2"] = new("ota", 23, 124),
        ["jk4"] = new("ota", 23, 128),
        ["jk5"] = new("ota", 23, 138),
        ["jk6"] = new("ota", 23, 131),
        ["jk7"] = new("ota", 23, 142),
        ["jk8"] = new("ota", 23, 134),
        ["jk9"] = new("ota", 23, 399),
        ["jk10"] = new("ota", 29, 426),
        ["jk11"] = new("ota", 24, 404),
        ["jk12"] = new("ota", 27, 417),
        ["jk13"] = new("ota", 42, 593),
        ["jk14"] = new("ota", 41, 588),
        ["jk101"] = new("bs", 23, 1),
        ["jk141"] = new("bs", 23, 5),
        ["jk151"] = new("bs", 23, 8),
        ["jk161"] = new("bs", 23, 11),
        ["jk171"] = new("bs", 23, 14),
        ["jk181"] = new("bs", 23, 17),
        ["jk191"] = new("bs", 23, 20),
        ["jk192"] = new("bs", 23, 21),
        ["jk193"] = new("bs", 23, 22),
        ["jk200"] = new("bs", 23, 23),
        ["jk201"] = new("bs", 23, 24),
        ["jk211"] = new("bs", 23, 26),
        ["jk222"] = new("bs", 23, 27),
        ["jk231"] = new("bs", 23, 28),
        ["jk232"] = new("bs", 23, 29),
        ["jk234"] = new("bs", 23, 30),
        ["jk236"] = new("bs", 23, 31),
        ["jk242"] = new("bs", 23, 34),
        ["jk243"] = new("bs", 23, 35),
        ["jk244"] = new("bs", 23, 36),
        ["jk245"] = new("bs", 23, 37),
        ["jk251"] = new("bs", 23, 38),
        ["jk252"] = new("bs", 23, 39),
        ["jk255"] = new("bs", 23, 40),
        ["jk256"] = new("bs", 23, 41),
        ["jk260"] = new("bs", 23, 260),
        ["jk265"] = new("bs", 23, 265),
    };

    private static readonly IReadOnlyDictionary<string, string> JikkyoToNhkService = new Dictionary<string, string>
    {
        ["jk1"]   = "g1",
        ["jk2"]   = "e1",
        ["jk102"] = "s2",
        ["jk103"] = "s5",
        ["jk104"] = "s6",
    };

    public ProgramInfoService(IConfiguration config, ILogger<ProgramInfoService> logger,
        ChannelsStreamBroadcaster broadcaster, ChannelCatalog channelCatalog,
        EpgStorageService epgStorage, EpgSourceRegistry sources, EpgSourceMonitor sourceMonitor)
    {
        _config = config;
        _logger = logger;
        _broadcaster = broadcaster;
        _channelCatalog = channelCatalog;
        _epgStorage = epgStorage;
        _sources = sources;
        _sourceMonitor = sourceMonitor;
        _timeZone = ResolveTimeZone(config["CacheServer:BroadcastTimeZone"] ?? "Asia/Tokyo");
        _nhkArea = config["CacheServer:NhkProgramApi:Area"] ?? "130";
        _http = new HttpClient(new SocketsHttpHandler
        {
            PooledConnectionLifetime = TimeSpan.FromMinutes(5),
            AutomaticDecompression = System.Net.DecompressionMethods.All,
        })
        { Timeout = TimeSpan.FromSeconds(15) };
        _http.DefaultRequestHeaders.TryAddWithoutValidation("Accept", "*/*");
        _http.DefaultRequestHeaders.TryAddWithoutValidation("Accept-Language", "ja");
        _http.DefaultRequestHeaders.TryAddWithoutValidation("Origin", "https://tver.jp");
        _http.DefaultRequestHeaders.TryAddWithoutValidation("Referer", "https://tver.jp/");
        _http.DefaultRequestHeaders.TryAddWithoutValidation("User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36");
        _http.DefaultRequestHeaders.TryAddWithoutValidation("X-TVer-Platform-Type", "web");
    }

    public ProgramInfo? GetProgram(string video)
    {
        lock (_lock)
            return _currentPrograms.TryGetValue(video, out var program) ? program : null;
    }

    public object CreateProgramsPayload() => new
    {
        type = "programs",
        updatedAt = FormatServerTime(),
        channels = _channelCatalog.All.Select(info => new
        {
            id = info.Id,
            video = info.Video,
            program = ToApiProgram(GetProgram(info.Video)),
        }),
    };

    public object CreateSchedulePayload(DateOnly? requestedBroadcastDate)
    {
        var broadcastDate = requestedBroadcastDate ?? GetBroadcastDate(DateTimeOffset.UtcNow);
        var rangeStart = CreateBroadcastBoundary(broadcastDate);
        var rangeEnd = CreateBroadcastBoundary(broadcastDate.AddDays(1));

        Dictionary<string, List<EpgProgram>> epgPrograms;
        DateTimeOffset cacheUpdatedAt;
        bool loaded;
        lock (_lock)
        {
            loaded = _loadedBroadcastDates.Contains(broadcastDate);
            cacheUpdatedAt = _lastFetchUtc;
            epgPrograms = loaded
                ? _epgPrograms.ToDictionary(
                    kv => kv.Key,
                    kv => kv.Value
                        .Where(program => program.EndAt > rangeStart && program.StartAt < rangeEnd)
                        .OrderBy(program => program.StartAt)
                        .ToList(),
                    StringComparer.Ordinal)
                : new Dictionary<string, List<EpgProgram>>(StringComparer.Ordinal);
        }

        if (!loaded)
        {
            var stored = _epgStorage.QueryPrograms(rangeStart, rangeEnd);
            if (stored.Count > 0)
            {
                epgPrograms = stored;
                loaded = true;
                cacheUpdatedAt = DateTimeOffset.MinValue;
            }
        }

        if (OverlayImportedPrograms(epgPrograms, rangeStart, rangeEnd))
            loaded = true;

        return new
        {
            date = $"{broadcastDate:yyyy-MM-dd}",
            broadcastStartHour = 5,
            startAt = rangeStart.ToString("yyyy-MM-ddTHH:mm:sszzz"),
            endAt = rangeEnd.ToString("yyyy-MM-ddTHH:mm:sszzz"),
            loaded,
            updatedAt = cacheUpdatedAt == DateTimeOffset.MinValue
                ? null
                : TimeZoneInfo.ConvertTime(cacheUpdatedAt, _timeZone).ToString("yyyy-MM-ddTHH:mm:ss.fffzzz"),
            channels = _channelCatalog.All.Select(info => new
            {
                id = info.Id,
                video = info.Video,
                name = info.Name,
                bs = info.Bs,
                programs = ResolveSchedulePrograms(epgPrograms, info.Video)
                    .Select(ToApiEpgProgram).ToArray()
            }),
        };
    }

    public object CreateStatusPayload()
    {
        int channels;
        int programs;
        lock (_lock)
        {
            channels = _epgPrograms.Count;
            programs = _epgPrograms.Values.Sum(items => items.Count);
        }
        var interval = TimeSpan.FromSeconds(Math.Max(60,
            _config.GetValue<int>("CacheServer:ProgramInfoUpdateIntervalSeconds", 1200)));
        static string? Stamp(DateTimeOffset value) => value == DateTimeOffset.MinValue ? null : value.ToString("O");
        object Source(IEpgSource source, DateTimeOffset legacyLastSuccess)
        {
            var enabled = source.IsEnabled(_config);
            var observed = _sourceMonitor.Get(source.Key);
            var lastSuccess = observed.LastSuccessAt ??
                (legacyLastSuccess == DateTimeOffset.MinValue ? null : legacyLastSuccess);
            return new
            {
                key = source.Key,
                name = source.Name,
                enabled,
                state = !enabled ? "disabled" : observed.ConsecutiveFailures > 0 ? "error" :
                    lastSuccess == null ? "waiting" : "ok",
                lastAttemptAt = observed.LastAttemptAt?.ToString("O"),
                lastSuccessAt = lastSuccess?.ToString("O"),
                lastFailureAt = observed.LastFailureAt?.ToString("O"),
                durationMs = observed.DurationMs,
                itemCount = observed.ItemCount,
                consecutiveFailures = observed.ConsecutiveFailures,
                error = observed.Error,
            };
        }
        return new
        {
            refreshing = _refreshLock.CurrentCount == 0,
            lastSuccessAt = Stamp(_lastFetchUtc),
            lastFailureAt = Stamp(_lastRefreshFailureUtc),
            nextScheduledAt = _lastFetchUtc == DateTimeOffset.MinValue ? null : Stamp(_lastFetchUtc.Add(interval)),
            cachedChannels = channels,
            cachedPrograms = programs,
            sources = new[]
            {
                Source(_sources["tver"], _lastFetchUtc),
                Source(_sources["nhk"], _lastNhkFetchUtc),
                Source(_sources["atx"], _lastAtxFetchUtc),
                Source(_sources["ouj"], _lastOujFetchUtc),
                Source(_sources["bs4"], _lastBs4SubChannelFetchUtc),
                Source(_sources["bstbs"], _lastBsTbsSubChannelFetchUtc),
                Source(_sources["bsfuji"], _lastBsFujiSubChannelFetchUtc),
            }
        };
    }

    public async Task<object> RefreshNowAsync(CancellationToken ct)
    {
        try
        {
            await RunRefreshLockedAsync(GetBroadcastDate(DateTimeOffset.UtcNow), ct);
            _lastRefreshFailureUtc = DateTimeOffset.MinValue;
            EvaluateCurrentPrograms(DateTimeOffset.UtcNow);
            return CreateStatusPayload();
        }
        catch
        {
            _lastRefreshFailureUtc = DateTimeOffset.UtcNow;
            throw;
        }
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var refreshInterval = TimeSpan.FromSeconds(Math.Max(60,
            _config.GetValue<int>("CacheServer:ProgramInfoUpdateIntervalSeconds", 1200)));
        var failureRetryInterval = TimeSpan.FromSeconds(Math.Max(300,
            _config.GetValue<int>("CacheServer:ProgramInfoFailureRetrySeconds", 1800)));
        var evaluationInterval = TimeSpan.FromSeconds(Math.Max(10,
            _config.GetValue<int>("CacheServer:ProgramInfoEvaluationIntervalSeconds", 60)));

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                var now = DateTimeOffset.UtcNow;
                var broadcastDate = GetBroadcastDate(now);
                var hasLoaded = HasLoadedBroadcastDates(broadcastDate);
                if (!hasLoaded || now - _lastFetchUtc >= refreshInterval)
                {
                    if (now - _lastRefreshFailureUtc >= failureRetryInterval)
                    {
                        if (hasLoaded && await DelayIfEpgUpdateAvoidWindowAsync(now, stoppingToken))
                        {
                            now = DateTimeOffset.UtcNow;
                            broadcastDate = GetBroadcastDate(now);
                        }
                        await RunRefreshLockedAsync(broadcastDate, stoppingToken);
                        _lastRefreshFailureUtc = DateTimeOffset.MinValue;
                    }
                }

                if (EvaluateCurrentPrograms(now))
                {
                    await _broadcaster.BroadcastAsync(CreateProgramsPayload(), stoppingToken);
                    _hasBroadcastSnapshot = true;
                }
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { break; }
            catch (Exception ex)
            {
                _lastRefreshFailureUtc = DateTimeOffset.UtcNow;
                _logger.LogWarning(ex, "[ProgramInfo] 番組情報更新に失敗しました");
                MarkCurrentProgramsStale();
            }

            try { await Task.Delay(evaluationInterval, stoppingToken); }
            catch (OperationCanceledException) { break; }
        }
    }

    // TVer/NHK/AT-X等の外部APIがどこかで応答せず固まった場合に、ExecuteAsync の
    // ループ自体が無期限に停止して _lastFetchUtc が更新されなくなるのを防ぐためのタイムアウト。
    // stoppingToken 自体のキャンセル（アプリ終了）とタイムアウトを区別し、タイムアウト時は
    // 通常の失敗として ExecuteAsync 側のリトライ処理に委ねる。
    private async Task RefreshEpgWithTimeoutAsync(DateOnly broadcastDate, CancellationToken stoppingToken)
    {
        var timeout = TimeSpan.FromSeconds(Math.Max(30,
            _config.GetValue<int>("CacheServer:ProgramInfoRefreshTimeoutSeconds", 120)));
        using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(stoppingToken);
        timeoutCts.CancelAfter(timeout);
        try
        {
            await RefreshEpgAsync(broadcastDate, timeoutCts.Token);
        }
        catch (OperationCanceledException) when (!stoppingToken.IsCancellationRequested)
        {
            throw new TimeoutException($"[ProgramInfo] EPG refresh timed out after {timeout}");
        }
    }

    private async Task RunRefreshLockedAsync(DateOnly broadcastDate, CancellationToken ct)
    {
        await _refreshLock.WaitAsync(ct);
        try { await RefreshEpgWithTimeoutAsync(broadcastDate, ct); }
        finally { _refreshLock.Release(); }
    }

    private async Task RefreshEpgAsync(DateOnly broadcastDate, CancellationToken ct)
    {
        var newEpgPrograms = new Dictionary<string, List<EpgProgram>>();
        var jikkyoToTVer = CreateTVerProgramMap();
        var targets = jikkyoToTVer.Values.Select(info => (info.Type, info.Area)).Distinct().ToArray();

        await _sourceMonitor.ObserveAsync("tver", async () =>
        {
            await FetchTVerProgramsAsync(broadcastDate, newEpgPrograms, jikkyoToTVer, targets, ct);
            await FetchTVerProgramsAsync(broadcastDate.AddDays(1), newEpgPrograms, jikkyoToTVer, targets, ct);
            return newEpgPrograms.Values.Sum(programs => programs.Count) > 0;
        }, () => newEpgPrograms.Values.Sum(programs => programs.Count));

        var now = DateTimeOffset.UtcNow;
        var nhkRefreshInterval = TimeSpan.FromSeconds(Math.Max(3600,
            _config.GetValue<int>("CacheServer:NhkProgramApi:UpdateIntervalSeconds", 43200)));
        var nhkFailureRetryInterval = TimeSpan.FromSeconds(Math.Max(300,
            _config.GetValue<int>("CacheServer:NhkProgramApi:FailureRetrySeconds", 1800)));

        if (_loadedNhkBroadcastDate != broadcastDate || now - _lastNhkFetchUtc >= nhkRefreshInterval)
        {
            if (now - _lastNhkAttemptUtc >= nhkFailureRetryInterval)
            {
                _lastNhkAttemptUtc = now;
                if (await ObserveSourceAsync("nhk", () => FetchNhkProgramsAsync(broadcastDate, newEpgPrograms, ct),
                    newEpgPrograms, JikkyoToNhkService.Keys))
                {
                    CopyMissingExistingNhkPrograms(broadcastDate, newEpgPrograms);
                    _loadedNhkBroadcastDate = broadcastDate;
                    _lastNhkFetchUtc = now;
                }
                else
                {
                    CopyExistingNhkPrograms(broadcastDate, newEpgPrograms);
                }
            }
            else
            {
                CopyExistingNhkPrograms(broadcastDate, newEpgPrograms);
            }
        }
        else
        {
            CopyExistingNhkPrograms(broadcastDate, newEpgPrograms);
        }

        var atxRefreshInterval = TimeSpan.FromSeconds(Math.Max(21600,
            _config.GetValue<int>("CacheServer:AtxProgram:UpdateIntervalSeconds", 86400)));
        var atxFailureRetryInterval = TimeSpan.FromSeconds(Math.Max(300,
            _config.GetValue<int>("CacheServer:AtxProgram:FailureRetrySeconds", 1800)));
        if (_config.GetValue<bool>("CacheServer:AtxProgram:Enabled", true) &&
            (_loadedAtxBroadcastDate != broadcastDate || now - _lastAtxFetchUtc >= atxRefreshInterval))
        {
            if (now - _lastAtxAttemptUtc >= atxFailureRetryInterval)
            {
                _lastAtxAttemptUtc = now;
                if (await ObserveSourceAsync("atx", () => FetchAtxProgramsAsync(broadcastDate, newEpgPrograms, ct),
                    newEpgPrograms, ["jk333"]))
                {
                    _loadedAtxBroadcastDate = broadcastDate;
                    _lastAtxFetchUtc = now;
                }
                else
                {
                    CopyExistingAtxPrograms(broadcastDate, newEpgPrograms);
                }
            }
            else
            {
                CopyExistingAtxPrograms(broadcastDate, newEpgPrograms);
            }
        }
        else
        {
            CopyExistingAtxPrograms(broadcastDate, newEpgPrograms);
        }

        var oujRefreshInterval = TimeSpan.FromSeconds(Math.Max(3600,
            _config.GetValue<int>("CacheServer:OujProgram:UpdateIntervalSeconds", 43200)));
        var oujFailureRetryInterval = TimeSpan.FromSeconds(Math.Max(300,
            _config.GetValue<int>("CacheServer:OujProgram:FailureRetrySeconds", 1800)));
        if (_config.GetValue<bool>("CacheServer:OujProgram:Enabled", true) &&
            (_loadedOujBroadcastDate != broadcastDate || now - _lastOujFetchUtc >= oujRefreshInterval))
        {
            if (now - _lastOujAttemptUtc >= oujFailureRetryInterval)
            {
                _lastOujAttemptUtc = now;
                if (await ObserveSourceAsync("ouj", () => FetchOujProgramsAsync(broadcastDate, newEpgPrograms, ct),
                    newEpgPrograms, ["jk531"]))
                {
                    _loadedOujBroadcastDate = broadcastDate;
                    _lastOujFetchUtc = now;
                }
                else
                {
                    CopyExistingOujPrograms(broadcastDate, newEpgPrograms);
                }
            }
            else
            {
                CopyExistingOujPrograms(broadcastDate, newEpgPrograms);
            }
        }
        else
        {
            CopyExistingOujPrograms(broadcastDate, newEpgPrograms);
        }

        var bs4RefreshInterval = TimeSpan.FromSeconds(Math.Max(3600,
            _config.GetValue<int>("CacheServer:Bs4SubChannelProgram:UpdateIntervalSeconds", 21600)));
        var bs4FailureRetryInterval = TimeSpan.FromSeconds(Math.Max(300,
            _config.GetValue<int>("CacheServer:Bs4SubChannelProgram:FailureRetrySeconds", 1800)));
        if (_config.GetValue<bool>("CacheServer:Bs4SubChannelProgram:Enabled", true) &&
            (_loadedBs4SubChannelBroadcastDate != broadcastDate || now - _lastBs4SubChannelFetchUtc >= bs4RefreshInterval))
        {
            if (now - _lastBs4SubChannelAttemptUtc >= bs4FailureRetryInterval)
            {
                _lastBs4SubChannelAttemptUtc = now;
                if (await ObserveSourceAsync("bs4", () => FetchBs4SubChannelProgramsAsync(broadcastDate, newEpgPrograms, ct),
                    newEpgPrograms, [_config["CacheServer:Bs4SubChannelProgram:ChannelVideo"] ?? "jk142"]))
                {
                    _loadedBs4SubChannelBroadcastDate = broadcastDate;
                    _lastBs4SubChannelFetchUtc = now;
                }
                else
                {
                    CopyExistingBs4SubChannelPrograms(broadcastDate, newEpgPrograms);
                }
            }
            else
            {
                CopyExistingBs4SubChannelPrograms(broadcastDate, newEpgPrograms);
            }
        }
        else
        {
            CopyExistingBs4SubChannelPrograms(broadcastDate, newEpgPrograms);
        }

        var bsTbsRefreshInterval = TimeSpan.FromSeconds(Math.Max(3600,
            _config.GetValue<int>("CacheServer:BsTbsSubChannelProgram:UpdateIntervalSeconds", 21600)));
        var bsTbsFailureRetryInterval = TimeSpan.FromSeconds(Math.Max(300,
            _config.GetValue<int>("CacheServer:BsTbsSubChannelProgram:FailureRetrySeconds", 1800)));
        if (_config.GetValue<bool>("CacheServer:BsTbsSubChannelProgram:Enabled", true) &&
            (_loadedBsTbsSubChannelBroadcastDate != broadcastDate || now - _lastBsTbsSubChannelFetchUtc >= bsTbsRefreshInterval))
        {
            if (now - _lastBsTbsSubChannelAttemptUtc >= bsTbsFailureRetryInterval)
            {
                _lastBsTbsSubChannelAttemptUtc = now;
                if (await ObserveSourceAsync("bstbs", () => FetchBsTbsSubChannelProgramsAsync(broadcastDate, newEpgPrograms, ct),
                    newEpgPrograms, [_config["CacheServer:BsTbsSubChannelProgram:ChannelVideo"] ?? "jk162"]))
                {
                    _loadedBsTbsSubChannelBroadcastDate = broadcastDate;
                    _lastBsTbsSubChannelFetchUtc = now;
                }
                else
                {
                    CopyExistingBsTbsSubChannelPrograms(broadcastDate, newEpgPrograms);
                }
            }
            else
            {
                CopyExistingBsTbsSubChannelPrograms(broadcastDate, newEpgPrograms);
            }
        }
        else
        {
            CopyExistingBsTbsSubChannelPrograms(broadcastDate, newEpgPrograms);
        }

        var bsFujiRefreshInterval = TimeSpan.FromSeconds(Math.Max(3600,
            _config.GetValue<int>("CacheServer:BsFujiSubChannelProgram:UpdateIntervalSeconds", 21600)));
        var bsFujiFailureRetryInterval = TimeSpan.FromSeconds(Math.Max(300,
            _config.GetValue<int>("CacheServer:BsFujiSubChannelProgram:FailureRetrySeconds", 1800)));
        if (_config.GetValue<bool>("CacheServer:BsFujiSubChannelProgram:Enabled", true) &&
            (_loadedBsFujiSubChannelBroadcastDate != broadcastDate || now - _lastBsFujiSubChannelFetchUtc >= bsFujiRefreshInterval))
        {
            if (now - _lastBsFujiSubChannelAttemptUtc >= bsFujiFailureRetryInterval)
            {
                _lastBsFujiSubChannelAttemptUtc = now;
                if (await ObserveSourceAsync("bsfuji", () => FetchBsFujiSubChannelProgramsAsync(broadcastDate, newEpgPrograms, ct),
                    newEpgPrograms, [_config["CacheServer:BsFujiSubChannelProgram:ChannelVideo"] ?? "jk182"]))
                {
                    _loadedBsFujiSubChannelBroadcastDate = broadcastDate;
                    _lastBsFujiSubChannelFetchUtc = now;
                }
                else
                {
                    CopyExistingBsFujiSubChannelPrograms(broadcastDate, newEpgPrograms);
                }
            }
            else
            {
                CopyExistingBsFujiSubChannelPrograms(broadcastDate, newEpgPrograms);
            }
        }
        else
        {
            CopyExistingBsFujiSubChannelPrograms(broadcastDate, newEpgPrograms);
        }

        OverlayImportedPrograms(newEpgPrograms,
            CreateBroadcastBoundary(broadcastDate),
            CreateBroadcastBoundary(broadcastDate.AddDays(2)));

        lock (_lock)
        {
            _epgPrograms.Clear();
            foreach (var (jkId, programs) in newEpgPrograms)
                _epgPrograms[jkId] = programs.OrderBy(program => program.StartAt).ToList();
            _loadedBroadcastDates.Clear();
            _loadedBroadcastDates.Add(broadcastDate);
            _loadedBroadcastDates.Add(broadcastDate.AddDays(1));
            _lastFetchUtc = DateTimeOffset.UtcNow;
        }

        foreach (var (jkId, programs) in newEpgPrograms)
            _epgStorage.SavePrograms(jkId, programs);

        _logger.LogDebug("[ProgramInfo] EPG を更新しました: {Date}-{NextDate} ({Count} channels)",
            broadcastDate, broadcastDate.AddDays(1), newEpgPrograms.Count);
    }

    private Task<bool> ObserveSourceAsync(string key, Func<Task<bool>> operation,
        IReadOnlyDictionary<string, List<EpgProgram>> programs, IEnumerable<string> channels) =>
        _sourceMonitor.ObserveAsync(key, operation,
            () => channels.Distinct(StringComparer.Ordinal)
                .Where(programs.ContainsKey).Sum(channel => programs[channel].Count));

    public async Task<(int ImportedCount, bool CurrentChanged)> ImportProgramsAsync(
        string channel,
        IReadOnlyList<EpgProgram> programs,
        CancellationToken ct)
    {
        var normalized = programs
            .Where(program => !string.IsNullOrWhiteSpace(program.Title) && program.EndAt > program.StartAt)
            .OrderBy(program => program.StartAt)
            .ToList();
        if (normalized.Count == 0)
            return (0, false);

        _epgStorage.ReplaceImportedPrograms(channel, normalized);

        var imported = new Dictionary<string, List<EpgProgram>>(StringComparer.Ordinal)
        {
            [channel] = normalized
        };
        lock (_lock)
        {
            OverlayProgramMap(_epgPrograms, imported);
            _lastImportUtc = DateTimeOffset.UtcNow;
        }

        var changed = EvaluateCurrentPrograms(DateTimeOffset.UtcNow);
        if (changed)
            await _broadcaster.BroadcastAsync(CreateProgramsPayload(), ct);

        _logger.LogInformation("[ProgramInfo] 外部EPGを取り込みました: channel={Channel} count={Count} start={Start} end={End}",
            channel, normalized.Count, normalized.First().StartAt, normalized.Last().EndAt);
        return (normalized.Count, changed);
    }

    private async Task<bool> DelayIfEpgUpdateAvoidWindowAsync(DateTimeOffset nowUtc, CancellationToken ct)
    {
        if (!_config.GetValue<bool>("CacheServer:EpgUpdateAvoidWindow:Enabled", true))
            return false;

        var startText = _config["CacheServer:EpgUpdateAvoidWindow:Start"] ?? "04:55";
        var endText = _config["CacheServer:EpgUpdateAvoidWindow:End"] ?? "05:10";
        if (!TimeOnly.TryParse(startText, out var start) ||
            !TimeOnly.TryParse(endText, out var end))
        {
            _logger.LogWarning("[ProgramInfo] EPG 更新回避時間帯の設定を解析できません: start={Start} end={End}",
                startText, endText);
            return false;
        }

        var localNow = TimeZoneInfo.ConvertTime(nowUtc, _timeZone);
        var localTime = TimeOnly.FromDateTime(localNow.DateTime);
        if (!IsTimeInWindow(localTime, start, end))
            return false;

        var endDate = DateOnly.FromDateTime(localNow.DateTime);
        if (end <= start && localTime >= start)
            endDate = endDate.AddDays(1);
        var delayUntilLocal = new DateTimeOffset(endDate.ToDateTime(end),
            _timeZone.GetUtcOffset(endDate.ToDateTime(end)));
        var delay = delayUntilLocal - localNow;
        if (delay <= TimeSpan.Zero)
            return false;

        _logger.LogInformation("[ProgramInfo] EPG 更新回避時間帯のため取得を延期します: now={Now} until={Until} delay={DelaySeconds}s",
            localNow.ToString("HH:mm:ss"), delayUntilLocal.ToString("HH:mm:ss"), Math.Ceiling(delay.TotalSeconds));
        await Task.Delay(delay, ct);
        return true;
    }

    private async Task FetchTVerProgramsAsync(DateOnly broadcastDate,
        Dictionary<string, List<EpgProgram>> epgPrograms,
        IReadOnlyDictionary<string, TVerBroadcasterInfo> jikkyoToTVer,
        (string Type, int Area)[] targets,
        CancellationToken ct)
    {
        foreach (var (type, area) in targets)
        {
            var urlDate = HttpUtility.UrlEncode($"{broadcastDate:yyyy/MM/dd}");
            var url = $"https://service-api.tver.jp/api/v1/callEPGv2?date={urlDate}&area={area}&type={type}";
            _logger.LogDebug("[ProgramInfo] TVer EPG を取得します: date={Date} area={Area} type={Type}",
                broadcastDate, area, type);
            using var response = await _http.GetAsync(url, ct);
            response.EnsureSuccessStatusCode();

            await using var stream = await response.Content.ReadAsStreamAsync(ct);
            using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: ct);
            if (!doc.RootElement.TryGetProperty("result", out var result) ||
                !result.TryGetProperty("contents", out var contents) ||
                contents.ValueKind != JsonValueKind.Array)
                continue;

            foreach (var content in contents.EnumerateArray())
            {
                if (!content.TryGetProperty("broadcaster", out var broadcaster) ||
                    !broadcaster.TryGetProperty("id", out var broadcasterIdElement) ||
                    !int.TryParse(broadcasterIdElement.GetString(), out var broadcasterId))
                    continue;

                var jkIds = jikkyoToTVer
                    .Where(kv => kv.Value.Type == type && kv.Value.Area == area && kv.Value.BroadcasterId == broadcasterId)
                    .Select(kv => kv.Key)
                    .ToArray();
                if (jkIds.Length == 0) continue;

                var programs = ParsePrograms(content);
                foreach (var jkId in jkIds)
                    AddPrograms(epgPrograms, jkId, programs);
            }
        }
    }

    private bool HasLoadedBroadcastDates(DateOnly broadcastDate)
    {
        lock (_lock)
            return _loadedBroadcastDates.Contains(broadcastDate) &&
                _loadedBroadcastDates.Contains(broadcastDate.AddDays(1));
    }

    private static void AddPrograms(Dictionary<string, List<EpgProgram>> epgPrograms,
        string jkId, IEnumerable<EpgProgram> programs)
    {
        if (!epgPrograms.TryGetValue(jkId, out var list))
        {
            list = new List<EpgProgram>();
            epgPrograms[jkId] = list;
        }
        list.AddRange(programs);
    }

    private bool OverlayImportedPrograms(Dictionary<string, List<EpgProgram>> epgPrograms,
        DateTimeOffset from, DateTimeOffset to)
    {
        var importedPrograms = _epgStorage.QueryImportedPrograms(from, to);
        if (importedPrograms.Count == 0)
            return false;

        OverlayProgramMap(epgPrograms, importedPrograms);
        return true;
    }

    private static void OverlayProgramMap(Dictionary<string, List<EpgProgram>> basePrograms,
        IReadOnlyDictionary<string, List<EpgProgram>> importedPrograms)
    {
        foreach (var (channel, overlayPrograms) in importedPrograms)
        {
            if (overlayPrograms.Count == 0)
                continue;

            var rangeStart = overlayPrograms.Min(program => program.StartAt);
            var rangeEnd = overlayPrograms.Max(program => program.EndAt);

            if (!basePrograms.TryGetValue(channel, out var existingPrograms))
                existingPrograms = new List<EpgProgram>();
            else
                existingPrograms = existingPrograms
                    .Where(program => program.EndAt <= rangeStart || program.StartAt >= rangeEnd)
                    .ToList();

            existingPrograms.AddRange(overlayPrograms);
            basePrograms[channel] = existingPrograms
                .OrderBy(program => program.StartAt)
                .ThenBy(program => program.EndAt)
                .ToList();
        }
    }

    private IReadOnlyDictionary<string, TVerBroadcasterInfo> CreateTVerProgramMap()
    {
        var map = new Dictionary<string, TVerBroadcasterInfo>(JikkyoToTVer, StringComparer.Ordinal);
        foreach (var section in _config.GetSection("CacheServer:TVerProgramMap").GetChildren())
        {
            var type = section.GetValue<string>("Type");
            var area = section.GetValue<int?>("Area");
            var broadcasterId = section.GetValue<int?>("BroadcasterId");
            if (string.IsNullOrWhiteSpace(type) || area == null || broadcasterId == null)
            {
                _logger.LogWarning("[ProgramInfo] TVerProgramMap の設定をスキップします: channel={Channel}", section.Key);
                continue;
            }

            map[section.Key] = new TVerBroadcasterInfo(type, area.Value, broadcasterId.Value);
        }

        return map;
    }

    private void CopyExistingNhkPrograms(DateOnly broadcastDate, Dictionary<string, List<EpgProgram>> epgPrograms)
    {
        if (_loadedNhkBroadcastDate != broadcastDate)
            return;

        lock (_lock)
        {
            foreach (var jkId in JikkyoToNhkService.Keys)
            {
                if (_epgPrograms.TryGetValue(jkId, out var programs))
                    epgPrograms[jkId] = programs;
            }
        }
    }

    private void CopyMissingExistingNhkPrograms(DateOnly broadcastDate, Dictionary<string, List<EpgProgram>> epgPrograms)
    {
        if (_loadedNhkBroadcastDate != broadcastDate)
            return;

        lock (_lock)
        {
            foreach (var jkId in JikkyoToNhkService.Keys)
            {
                if (!epgPrograms.ContainsKey(jkId) && _epgPrograms.TryGetValue(jkId, out var programs))
                    epgPrograms[jkId] = programs;
            }
        }
    }

    private void CopyExistingAtxPrograms(DateOnly broadcastDate, Dictionary<string, List<EpgProgram>> epgPrograms)
    {
        if (_loadedAtxBroadcastDate != broadcastDate)
            return;

        lock (_lock)
        {
            if (_epgPrograms.TryGetValue("jk333", out var programs))
                epgPrograms["jk333"] = programs;
        }
    }

    private void CopyExistingOujPrograms(DateOnly broadcastDate, Dictionary<string, List<EpgProgram>> epgPrograms)
    {
        if (_loadedOujBroadcastDate != broadcastDate)
            return;

        lock (_lock)
        {
            if (_epgPrograms.TryGetValue("jk531", out var programs))
                epgPrograms["jk531"] = programs;
        }
    }

    private void CopyExistingBs4SubChannelPrograms(DateOnly broadcastDate, Dictionary<string, List<EpgProgram>> epgPrograms)
    {
        if (_loadedBs4SubChannelBroadcastDate != broadcastDate)
            return;

        var channelVideo = _config["CacheServer:Bs4SubChannelProgram:ChannelVideo"] ?? "jk142";
        lock (_lock)
        {
            if (_epgPrograms.TryGetValue(channelVideo, out var programs))
                epgPrograms[channelVideo] = programs;
        }
    }

    private void CopyExistingBsTbsSubChannelPrograms(DateOnly broadcastDate, Dictionary<string, List<EpgProgram>> epgPrograms)
    {
        if (_loadedBsTbsSubChannelBroadcastDate != broadcastDate)
            return;

        var channelVideo = _config["CacheServer:BsTbsSubChannelProgram:ChannelVideo"] ?? "jk162";
        lock (_lock)
        {
            if (_epgPrograms.TryGetValue(channelVideo, out var programs))
                epgPrograms[channelVideo] = programs;
        }
    }

    private void CopyExistingBsFujiSubChannelPrograms(DateOnly broadcastDate, Dictionary<string, List<EpgProgram>> epgPrograms)
    {
        if (_loadedBsFujiSubChannelBroadcastDate != broadcastDate)
            return;

        var channelVideo = _config["CacheServer:BsFujiSubChannelProgram:ChannelVideo"] ?? "jk182";
        lock (_lock)
        {
            if (_epgPrograms.TryGetValue(channelVideo, out var programs))
                epgPrograms[channelVideo] = programs;
        }
    }

    private async Task<bool> FetchAtxProgramsAsync(DateOnly broadcastDate,
        Dictionary<string, List<EpgProgram>> epgPrograms, CancellationToken ct)
    {
        var url = _config["CacheServer:AtxProgram:Url"] ?? "https://www.at-x.com/program";
        var apiUrl = _config["CacheServer:AtxProgram:ApiUrl"] ?? "https://api.atx.01core.app/api/schedules?id";
        try
        {
            _logger.LogDebug("[ProgramInfo] AT-X 番組表APIを取得します: url={Url}", apiUrl);
            var json = await _http.GetStringAsync(apiUrl, ct);
            var apiPrograms = ParseAtxApiPrograms(json);
            if (apiPrograms.Count > 0)
            {
                epgPrograms["jk333"] = apiPrograms;
                _logger.LogInformation("[ProgramInfo] AT-X 番組表を更新しました: source=api count={Count}",
                    apiPrograms.Count);
                return true;
            }
            _logger.LogWarning("[ProgramInfo] AT-X 番組表APIの解析結果が0件です: url={Url}", apiUrl);
        }
        catch (OperationCanceledException) { throw; }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "[ProgramInfo] AT-X 番組表API取得に失敗しました: url={Url}", apiUrl);
        }

        try
        {
            _logger.LogDebug("[ProgramInfo] AT-X 番組表を取得します: url={Url}", url);
            var html = await _http.GetStringAsync(url, ct);
            var programs = ParseAtxPrograms(html);
            if (programs.Count == 0)
            {
                _logger.LogWarning("[ProgramInfo] AT-X 番組表の解析結果が0件です: url={Url}", url);
                return false;
            }

            epgPrograms["jk333"] = programs;
            _logger.LogInformation("[ProgramInfo] AT-X 番組表を更新しました: source=html count={Count}", programs.Count);
            return true;
        }
        catch (OperationCanceledException) { throw; }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "[ProgramInfo] AT-X 番組表取得に失敗しました: url={Url}", url);
            return false;
        }
    }

    private async Task<bool> FetchBs4SubChannelProgramsAsync(DateOnly broadcastDate,
        Dictionary<string, List<EpgProgram>> epgPrograms, CancellationToken ct)
    {
        var url = _config["CacheServer:Bs4SubChannelProgram:TablePageUrl"] ??
            "https://rakuraku2.bangumi.org/tablePage";
        var pageUrl = _config["CacheServer:Bs4SubChannelProgram:PageUrl"] ??
            "https://www.bs4.jp/programschedule/142ch.html";
        var referer = _config["CacheServer:Bs4SubChannelProgram:Referer"] ?? "www.bs4.jp";
        var channelIndex = _config["CacheServer:Bs4SubChannelProgram:ChannelIndex"] ?? "3";
        var channelVideo = _config["CacheServer:Bs4SubChannelProgram:ChannelVideo"] ?? "jk142";

        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Post, url)
            {
                Content = new FormUrlEncodedContent(new Dictionary<string, string>
                {
                    ["platform"] = "D",
                    ["isSamplePage"] = "false",
                    ["referer"] = referer,
                    ["channelIndex"] = channelIndex,
                }),
            };
            request.Headers.TryAddWithoutValidation("Origin", "https://www.bs4.jp");
            request.Headers.TryAddWithoutValidation("Referer", pageUrl);
            request.Headers.TryAddWithoutValidation("Accept", "text/html, */*; q=0.1");

            _logger.LogDebug("[ProgramInfo] BS日テレサブチャンネル番組表を取得します: channel={Channel} url={Url}",
                channelVideo, url);
            using var response = await _http.SendAsync(request, ct);
            response.EnsureSuccessStatusCode();

            var html = await response.Content.ReadAsStringAsync(ct);
            var programs = ParseBs4SubChannelPrograms(html, channelVideo);
            if (programs.Count == 0)
            {
                _logger.LogWarning("[ProgramInfo] BS日テレサブチャンネル番組表の解析結果が0件です: channel={Channel}",
                    channelVideo);
                return false;
            }

            epgPrograms[channelVideo] = programs;
            _logger.LogInformation("[ProgramInfo] BS日テレサブチャンネル番組表を更新しました: channel={Channel} count={Count} date={Date}",
                channelVideo, programs.Count, broadcastDate);
            return true;
        }
        catch (OperationCanceledException) { throw; }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "[ProgramInfo] BS日テレサブチャンネル番組表取得に失敗しました: channel={Channel} url={Url}",
                channelVideo, url);
            return false;
        }
    }

    private async Task<bool> FetchBsTbsSubChannelProgramsAsync(DateOnly broadcastDate,
        Dictionary<string, List<EpgProgram>> epgPrograms, CancellationToken ct)
    {
        var url = _config["CacheServer:BsTbsSubChannelProgram:TablePageUrl"] ??
            "https://rakuraku2.bangumi.org/tablePage";
        var pageUrl = _config["CacheServer:BsTbsSubChannelProgram:PageUrl"] ??
            "https://bs.tbs.co.jp/epg_2k.html";
        var referer = _config["CacheServer:BsTbsSubChannelProgram:Referer"] ?? "bs.tbs.co.jp";
        var channelIndex = _config["CacheServer:BsTbsSubChannelProgram:ChannelIndex"] ?? "3";
        var channelVideo = _config["CacheServer:BsTbsSubChannelProgram:ChannelVideo"] ?? "jk162";

        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Post, url)
            {
                Content = new FormUrlEncodedContent(new Dictionary<string, string>
                {
                    ["platform"] = "D",
                    ["isSamplePage"] = "false",
                    ["referer"] = referer,
                    ["channelIndex"] = channelIndex,
                }),
            };
            request.Headers.TryAddWithoutValidation("Origin", "https://bs.tbs.co.jp");
            request.Headers.TryAddWithoutValidation("Referer", pageUrl);
            request.Headers.TryAddWithoutValidation("Accept", "text/html, */*; q=0.1");

            _logger.LogDebug("[ProgramInfo] BS-TBSサブチャンネル番組表を取得します: channel={Channel} url={Url}",
                channelVideo, url);
            using var response = await _http.SendAsync(request, ct);
            response.EnsureSuccessStatusCode();

            var html = await response.Content.ReadAsStringAsync(ct);
            var programs = ParseRakurakuSubChannelPrograms(html, "bstbs-subchannel");
            if (programs.Count == 0)
            {
                _logger.LogWarning("[ProgramInfo] BS-TBSサブチャンネル番組表の解析結果が0件です: channel={Channel}",
                    channelVideo);
                return false;
            }

            epgPrograms[channelVideo] = programs;
            _logger.LogInformation("[ProgramInfo] BS-TBSサブチャンネル番組表を更新しました: channel={Channel} count={Count} date={Date}",
                channelVideo, programs.Count, broadcastDate);
            return true;
        }
        catch (OperationCanceledException) { throw; }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "[ProgramInfo] BS-TBSサブチャンネル番組表取得に失敗しました: channel={Channel} url={Url}",
                channelVideo, url);
            return false;
        }
    }

    private async Task<bool> FetchBsFujiSubChannelProgramsAsync(DateOnly broadcastDate,
        Dictionary<string, List<EpgProgram>> epgPrograms, CancellationToken ct)
    {
        var nowTodayUrl = _config["CacheServer:BsFujiSubChannelProgram:NowTodayUrl"] ??
            "https://www.bsfuji.tv/top/timetable/epg/2K/now_today.txt";
        var jsonBaseUrl = _config["CacheServer:BsFujiSubChannelProgram:JsonBaseUrl"] ??
            "https://www.bsfuji.tv/top/timetable/epg/2K/json";
        var channelVideo = _config["CacheServer:BsFujiSubChannelProgram:ChannelVideo"] ?? "jk182";
        var channelNumber = _config["CacheServer:BsFujiSubChannelProgram:ChannelNumber"] ?? "182";

        try
        {
            _logger.LogDebug("[ProgramInfo] BSフジサブチャンネル日付情報を取得します: url={Url}", nowTodayUrl);
            var todayText = (await _http.GetStringAsync(nowTodayUrl, ct)).Trim();
            if (!Regex.IsMatch(todayText, @"^\d{8}$"))
            {
                _logger.LogWarning("[ProgramInfo] BSフジサブチャンネル日付情報の形式が不正です: value={Value}", todayText);
                return false;
            }

            var jsonTexts = new List<string>();
            foreach (var page in new[] { 1, 2 })
            {
                var jsonUrl = $"{jsonBaseUrl.TrimEnd('/')}/{todayText}_{page}.json";
                _logger.LogDebug("[ProgramInfo] BSフジサブチャンネル番組表JSONを取得します: channel={Channel} url={Url}",
                    channelVideo, jsonUrl);
                jsonTexts.Add(await _http.GetStringAsync(jsonUrl, ct));
            }

            var programs = ParseBsFujiSubChannelPrograms(jsonTexts, channelNumber);
            if (programs.Count == 0)
            {
                _logger.LogWarning("[ProgramInfo] BSフジサブチャンネル番組表の解析結果が0件です: channel={Channel}",
                    channelVideo);
                return false;
            }

            epgPrograms[channelVideo] = programs;
            _logger.LogInformation("[ProgramInfo] BSフジサブチャンネル番組表を更新しました: channel={Channel} count={Count} date={Date}",
                channelVideo, programs.Count, broadcastDate);
            return true;
        }
        catch (OperationCanceledException) { throw; }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "[ProgramInfo] BSフジサブチャンネル番組表取得に失敗しました: channel={Channel} nowTodayUrl={NowTodayUrl}",
                channelVideo, nowTodayUrl);
            return false;
        }
    }

    private async Task<bool> FetchNhkProgramsAsync(DateOnly broadcastDate,
        Dictionary<string, List<EpgProgram>> epgPrograms, CancellationToken ct)
    {
        var nhkApiKey = _config["CacheServer:NhkProgramApi:API_Key"]
            ?? _config["CacheServer:NhkProgramApi:ApiKey"];
        if (string.IsNullOrWhiteSpace(nhkApiKey))
        {
            _logger.LogInformation("[ProgramInfo] NHK 番組APIキーが未設定のため NHK EPG 取得をスキップします");
            return false;
        }

        var successCount = 0;
        foreach (var (jkId, service) in JikkyoToNhkService)
        {
            try
            {
                var url = "https://program-api.nhk.jp/v3/papiPgDateTv" +
                    $"?service={HttpUtility.UrlEncode(service)}" +
                    $"&area={HttpUtility.UrlEncode(_nhkArea)}" +
                    $"&date={broadcastDate:yyyy-MM-dd}" +
                    $"&key={HttpUtility.UrlEncode(nhkApiKey)}";

                _logger.LogDebug("[ProgramInfo] NHK EPG を取得します: date={Date} area={Area} service={Service}",
                    broadcastDate, _nhkArea, service);
                using var response = await _http.GetAsync(url, ct);
                _logger.LogDebug("[ProgramInfo] NHK EPG 応答: status={StatusCode} date={Date} area={Area} service={Service}",
                    (int)response.StatusCode, broadcastDate, _nhkArea, service);
                if (!response.IsSuccessStatusCode)
                {
                    var body = await response.Content.ReadAsStringAsync(ct);
                    _logger.LogWarning("[ProgramInfo] NHK EPG 取得 HTTP {StatusCode}: date={Date} area={Area} service={Service} body={Body}",
                        (int)response.StatusCode, broadcastDate, _nhkArea, service, TruncateLogBody(body));
                    continue;
                }

                await using var stream = await response.Content.ReadAsStreamAsync(ct);
                using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: ct);
                _logger.LogDebug("[ProgramInfo] NHK EPG JSON を解析しました: date={Date} area={Area} service={Service} keys={Keys}",
                    broadcastDate, _nhkArea, service, GetJsonKeys(doc.RootElement));
                if (!TryGetNhkProgramArray(doc.RootElement, service, out var programs))
                {
                    _logger.LogWarning("[ProgramInfo] NHK EPG に番組リストがありません: date={Date} area={Area} service={Service} keys={Keys}",
                        broadcastDate, _nhkArea, service, GetJsonKeys(doc.RootElement));
                    continue;
                }

                var parsedPrograms = ParseNhkPrograms(programs);
                if (parsedPrograms.Count == 0)
                {
                    _logger.LogWarning("[ProgramInfo] NHK EPG の番組解析結果が0件です: date={Date} area={Area} service={Service}",
                        broadcastDate, _nhkArea, service);
                    continue;
                }

                epgPrograms[jkId] = parsedPrograms;
                successCount++;
                _logger.LogInformation("[ProgramInfo] NHK EPG を更新しました: date={Date} area={Area} service={Service} channel={Channel} count={Count} genres={GenreCount}",
                    broadcastDate, _nhkArea, service, jkId, parsedPrograms.Count,
                    parsedPrograms.Count(program => program.GenreCode != null));
            }
            catch (OperationCanceledException) { throw; }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "[ProgramInfo] NHK EPG 取得に失敗しました: date={Date} area={Area} service={Service} errorType={ErrorType} error={Error}",
                    broadcastDate, _nhkArea, service, ex.GetType().Name, ex.Message);
            }
        }

        return successCount > 0;
    }

    private async Task<bool> FetchOujProgramsAsync(DateOnly broadcastDate,
        Dictionary<string, List<EpgProgram>> epgPrograms, CancellationToken ct)
    {
        var baseUrl = _config["CacheServer:OujProgram:Url"] ??
            "https://bangumi.ouj.ac.jp/v4/bslife/oujapi.php";
        var rangeStart = CreateBroadcastBoundary(broadcastDate);
        var rangeEnd = CreateBroadcastBoundary(broadcastDate.AddDays(2));
        var url = $"{baseUrl}?mode=list&ret=xml" +
            $"&fromtime={rangeStart:yyyyMMddHHmm}" +
            $"&totime={rangeEnd:yyyyMMddHHmm}" +
            "&ch=BS531";

        try
        {
            _logger.LogDebug("[ProgramInfo] 放送大学 EPG を取得します: channel=jk531 from={From} to={To}",
                rangeStart, rangeEnd);
            var xml = await _http.GetStringAsync(url, ct);
            var programs = ParseOujPrograms(xml);
            if (programs.Count == 0)
            {
                _logger.LogWarning("[ProgramInfo] 放送大学 EPG の解析結果が0件です: channel=jk531 url={Url}",
                    RedactOujUrl(url));
                return false;
            }

            epgPrograms["jk531"] = programs;
            _logger.LogInformation("[ProgramInfo] 放送大学 EPG を更新しました: channel=jk531 count={Count}",
                programs.Count);
            return true;
        }
        catch (OperationCanceledException) { throw; }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "[ProgramInfo] 放送大学 EPG 取得に失敗しました: channel=jk531 url={Url}",
                RedactOujUrl(url));
            return false;
        }
    }

    private static bool TryGetNhkProgramArray(JsonElement root, string service, out JsonElement programs)
    {
        if (root.TryGetProperty("list", out var list) &&
            list.TryGetProperty(service, out var listPrograms) &&
            listPrograms.ValueKind == JsonValueKind.Array)
        {
            programs = listPrograms;
            return true;
        }

        if (root.TryGetProperty(service, out var serviceElement))
        {
            if (serviceElement.ValueKind == JsonValueKind.Array)
            {
                programs = serviceElement;
                return true;
            }

            if (serviceElement.ValueKind == JsonValueKind.Object &&
                serviceElement.TryGetProperty("publication", out var publication) &&
                publication.ValueKind == JsonValueKind.Array)
            {
                programs = publication;
                return true;
            }
        }

        programs = default;
        return false;
    }

    private List<EpgProgram> ParsePrograms(JsonElement content)
    {
        var programs = new List<EpgProgram>();
        if (!content.TryGetProperty("programs", out var array) || array.ValueKind != JsonValueKind.Array)
            return programs;

        foreach (var program in array.EnumerateArray())
        {
            try
            {
                var title = program.TryGetProperty("title", out var titleElement)
                    ? FormatTitle(titleElement.GetString() ?? "", program)
                    : "";
                if (string.IsNullOrWhiteSpace(title)) continue;

                var startAt = DateTimeOffset.FromUnixTimeSeconds(program.GetProperty("startAt").GetInt64())
                    .ToOffset(_timeZone.GetUtcOffset(DateTimeOffset.UtcNow));
                var endAt = DateTimeOffset.FromUnixTimeSeconds(program.GetProperty("endAt").GetInt64())
                    .ToOffset(_timeZone.GetUtcOffset(DateTimeOffset.UtcNow));
                var genreCode = NormalizeGenreCode(GetStringProperty(program, "genre"));
                programs.Add(new EpgProgram(title, startAt, endAt, "tver", genreCode, GenreName(genreCode)));
            }
            catch (Exception ex)
            {
                _logger.LogDebug(ex, "[ProgramInfo] TVer 番組要素の解析をスキップしました");
            }
        }

        return programs.OrderBy(program => program.StartAt).ToList();
    }

    private List<EpgProgram> ParseNhkPrograms(JsonElement array)
    {
        var programs = new List<EpgProgram>();
        foreach (var program in array.EnumerateArray())
        {
            try
            {
                var title = GetStringProperty(program, "title", "name");
                if (string.IsNullOrWhiteSpace(title)) continue;

                if (!TryParseDateTimeOffsetProperty(program, out var startAt, "start_time", "startDate"))
                    continue;
                if (!TryParseDateTimeOffsetProperty(program, out var endAt, "end_time", "endDate"))
                    continue;

                var genreCode = GetNhkGenreCode(program);
                programs.Add(new EpgProgram(NormalizeTitle(title),
                    TimeZoneInfo.ConvertTime(startAt, _timeZone),
                    TimeZoneInfo.ConvertTime(endAt, _timeZone),
                    "nhk",
                    genreCode,
                    GenreName(genreCode)));
            }
            catch (Exception ex)
            {
                _logger.LogDebug(ex, "[ProgramInfo] NHK 番組要素の解析をスキップしました");
            }
        }

        return programs.OrderBy(program => program.StartAt).ToList();
    }

    private List<EpgProgram> ParseOujPrograms(string xml)
    {
        var programs = new List<EpgProgram>();
        var doc = XDocument.Parse(xml);
        foreach (var program in doc.Descendants("ProgramData"))
        {
            try
            {
                var title = program.Element("program_title")?.Value;
                if (string.IsNullOrWhiteSpace(title))
                    continue;

                foreach (var oa in program.Element("oa_info")?.Elements("oa") ?? Enumerable.Empty<XElement>())
                {
                    var channel = oa.Element("oa_ch")?.Value;
                    if (!string.Equals(channel, "BS531", StringComparison.OrdinalIgnoreCase))
                        continue;

                    if (!TryParseOujDateTime(oa.Element("oa_date")?.Value, oa.Element("oa_time_from")?.Value,
                            out var startAt))
                        continue;
                    if (!TryParseOujDateTime(oa.Element("oa_date")?.Value, oa.Element("oa_time_to")?.Value,
                            out var endAt))
                        continue;
                    if (endAt <= startAt)
                        endAt = endAt.AddDays(1);

                    programs.Add(new EpgProgram(
                        NormalizeTitle(title),
                        startAt,
                        endAt,
                        "ouj",
                        "0xF",
                        GenreName("0xF")));
                }
            }
            catch (Exception ex)
            {
                _logger.LogDebug(ex, "[ProgramInfo] 放送大学 番組要素の解析をスキップしました");
            }
        }

        return programs
            .GroupBy(program => (program.Title, program.StartAt, program.EndAt))
            .Select(group => group.First())
            .OrderBy(program => program.StartAt)
            .ToList();
    }

    private List<EpgProgram> ParseAtxApiPrograms(string json)
    {
        var startsByDate = new Dictionary<DateOnly, List<AtxProgramStart>>();
        using var doc = JsonDocument.Parse(json);
        if (!doc.RootElement.TryGetProperty("time_table", out var timeTable) ||
            timeTable.ValueKind != JsonValueKind.Array)
            return new List<EpgProgram>();

        foreach (var row in timeTable.EnumerateArray())
        {
            var timeText = GetStringProperty(row, "time");
            if (!TryParseAtxTime(timeText, out var hour, out var minute))
                continue;

            if (!row.TryGetProperty("programs", out var programs) ||
                programs.ValueKind != JsonValueKind.Array)
                continue;

            foreach (var program in programs.EnumerateArray())
            {
                try
                {
                    var dateText = GetStringProperty(program, "date");
                    if (!DateOnly.TryParse(dateText, out var date))
                        continue;

                    var title = FormatAtxApiTitle(
                        GetStringProperty(program, "program_title"),
                        GetStringProperty(program, "episode"),
                        program.TryGetProperty("type", out var typeElement) && typeElement.TryGetInt32(out var type)
                            ? type
                            : 0);
                    if (string.IsNullOrWhiteSpace(title))
                        continue;

                    if (!startsByDate.TryGetValue(date, out var list))
                    {
                        list = new List<AtxProgramStart>();
                        startsByDate[date] = list;
                    }
                    list.Add(new AtxProgramStart(CreateAtxStartTime(date, hour, minute), title));
                }
                catch (Exception ex)
                {
                    _logger.LogDebug(ex, "[ProgramInfo] AT-X API 番組要素の解析をスキップしました");
                }
            }
        }

        var result = new List<EpgProgram>();
        foreach (var (date, starts) in startsByDate)
        {
            var ordered = starts
                .GroupBy(program => (program.Title, program.StartAt))
                .Select(group => group.First())
                .OrderBy(program => program.StartAt)
                .ToArray();
            for (var i = 0; i < ordered.Length; i++)
            {
                var startAt = ordered[i].StartAt;
                var endAt = i + 1 < ordered.Length
                    ? ordered[i + 1].StartAt
                    : CreateAtxStartTime(date, 30, 0);
                if (endAt > startAt)
                    result.Add(new EpgProgram(ordered[i].Title, startAt, endAt, "atx", null, null));
            }
        }

        return result.OrderBy(program => program.StartAt).ToList();
    }

    private List<EpgProgram> ParseBs4SubChannelPrograms(string html, string channelVideo)
        => ParseRakurakuSubChannelPrograms(html, "bs4-subchannel");

    private List<EpgProgram> ParseRakurakuSubChannelPrograms(string html, string source)
    {
        var broadcastDates = Regex.Matches(html, @"data-date-string=""(?<date>\d{8})""",
                RegexOptions.Singleline | RegexOptions.IgnoreCase)
            .Cast<Match>()
            .Select(match => DateOnly.ParseExact(match.Groups["date"].Value, "yyyyMMdd"))
            .ToArray();
        var dayBlocks = Regex.Matches(html,
                @"<div class=""broadcaster_box\b[^""]*""[^>]*>\s*<ul>(?<body>.*?)</ul>\s*</div>",
                RegexOptions.Singleline | RegexOptions.IgnoreCase)
            .Cast<Match>()
            .Select(match => match.Groups["body"].Value)
            .ToArray();
        if (broadcastDates.Length == 0 || dayBlocks.Length == 0)
            return new List<EpgProgram>();

        var programs = new List<EpgProgram>();
        var dayCount = Math.Min(broadcastDates.Length, dayBlocks.Length);
        for (var dayIndex = 0; dayIndex < dayCount; dayIndex++)
        {
            var rows = new List<RakurakuProgramRow>();
            foreach (Match itemMatch in Regex.Matches(dayBlocks[dayIndex],
                         @"<li\b[^>]*data-program=""[^""]*""[^>]*>(?<body>.*?)</li>",
                         RegexOptions.Singleline | RegexOptions.IgnoreCase))
            {
                var attrs = itemMatch.Value;
                var body = itemMatch.Groups["body"].Value;
                var height = 0;
                var heightMatch = Regex.Match(attrs, @"height:\s*(?<height>\d+)px",
                    RegexOptions.IgnoreCase);
                if (heightMatch.Success)
                    int.TryParse(heightMatch.Groups["height"].Value, out height);

                var time = ExtractHtmlText(body, "time");
                var title = NormalizeTitle(ExtractHtmlText(body, "title"));
                var isDummy = attrs.Contains("dummy", StringComparison.OrdinalIgnoreCase);
                if (isDummy)
                {
                    rows.Add(new RakurakuProgramRow(null, null, null, null, Math.Max(1, height), true));
                    continue;
                }

                var href = Regex.Match(body, @"<a\b[^>]*href=""(?<href>[^""]+)""",
                    RegexOptions.Singleline | RegexOptions.IgnoreCase).Groups["href"].Value;
                if (string.IsNullOrWhiteSpace(href) ||
                    string.IsNullOrWhiteSpace(time) ||
                    string.IsNullOrWhiteSpace(title) ||
                    !TryParseAtxTime(time, out var hour, out var minute))
                    continue;

                var category = NormalizeTitle(ExtractHtmlText(body, "categoryt"));
                var genreCode = GenreCodeFromBs4Category(category);
                var startAt = CreateBs4StartTime(broadcastDates[dayIndex], hour, minute);
                rows.Add(new RakurakuProgramRow(startAt, title, genreCode, GenreName(genreCode), Math.Max(1, height), false));
            }

            var ordered = rows
                .Where(row => row.IsDummy || row.StartAt is not null)
                .ToArray();
            var programIndices = ordered
                .Select((row, index) => (row, index))
                .Where(entry => !entry.row.IsDummy && entry.row.StartAt is not null && !string.IsNullOrWhiteSpace(entry.row.Title))
                .Select(entry => entry.index)
                .ToArray();

            for (var i = 0; i < programIndices.Length; i++)
            {
                var currentIndex = programIndices[i];
                var current = ordered[currentIndex];
                var startAt = current.StartAt!.Value;

                var nextIndex = i + 1 < programIndices.Length
                    ? programIndices[i + 1]
                    : ordered.Length;
                var nextStartAt = i + 1 < programIndices.Length
                    ? ordered[nextIndex].StartAt!.Value
                    : CreateBs4BroadcastBoundary(broadcastDates[dayIndex].AddDays(1));

                DateTimeOffset endAt;
                var segment = ordered[currentIndex..nextIndex];
                if (segment.Length > 1)
                {
                    var totalHeight = segment.Sum(row => Math.Max(1, row.Height));
                    var totalSeconds = (nextStartAt - startAt).TotalSeconds;
                    if (totalHeight > 0 && totalSeconds > 0)
                    {
                        var currentSeconds = totalSeconds * Math.Max(1, current.Height) / totalHeight;
                        endAt = startAt.AddSeconds(currentSeconds);
                    }
                    else
                    {
                        endAt = nextStartAt;
                    }
                }
                else
                {
                    endAt = nextStartAt;
                }

                if (endAt <= startAt)
                    continue;

                programs.Add(new EpgProgram(
                    current.Title!,
                    startAt,
                    endAt,
                    source,
                    current.GenreCode,
                    current.GenreName));
            }
        }

        return programs.OrderBy(program => program.StartAt).ToList();
    }

    private sealed record RakurakuProgramRow(
        DateTimeOffset? StartAt,
        string? Title,
        string? GenreCode,
        string? GenreName,
        int Height,
        bool IsDummy);

    private List<EpgProgram> ParseBsFujiSubChannelPrograms(IEnumerable<string> jsonTexts, string channelNumber)
    {
        var programs = new List<EpgProgram>();

        foreach (var jsonText in jsonTexts)
        {
            using var doc = JsonDocument.Parse(jsonText);
            if (!doc.RootElement.TryGetProperty("days", out var days) ||
                days.ValueKind != JsonValueKind.Array)
                continue;

            foreach (var day in days.EnumerateArray())
            {
                var dateText = GetStringProperty(day, "date");
                if (!DateOnly.TryParseExact(dateText, "yyyyMMdd", out var date))
                    continue;
                if (!day.TryGetProperty("info", out var infoArray) ||
                    infoArray.ValueKind != JsonValueKind.Array)
                    continue;

                JsonElement? targetInfo = null;
                foreach (var info in infoArray.EnumerateArray())
                {
                    if (GetStringProperty(info, "ch") == channelNumber)
                    {
                        targetInfo = info;
                        break;
                    }
                }

                if (targetInfo is not JsonElement infoElement ||
                    !infoElement.TryGetProperty("program", out var programArray) ||
                    programArray.ValueKind != JsonValueKind.Array)
                    continue;

                foreach (var program in programArray.EnumerateArray())
                {
                    var title = NormalizeTitle(GetStringProperty(program, "title"));
                    if (string.IsNullOrWhiteSpace(title))
                        continue;

                    var startHourText = GetStringProperty(program, "start_hour");
                    var startMinText = GetStringProperty(program, "start_min");
                    var endTimeText = GetStringProperty(program, "end_time");
                    if (!int.TryParse(startHourText, out var startHour) ||
                        !int.TryParse(startMinText, out var startMinute) ||
                        !TryParseCompactTime(endTimeText, out var endHour, out var endMinute))
                        continue;

                    var startAt = CreateBsFujiStartTime(date, startHour, startMinute);
                    var endAt = CreateBsFujiStartTime(date, endHour, endMinute);
                    if (endAt <= startAt)
                        continue;

                    var genreCode = GenreCodeFromBsFujiCategory(
                        GetStringProperty(program, "genre_name"),
                        GetStringProperty(program, "genre"));
                    programs.Add(new EpgProgram(
                        title,
                        startAt,
                        endAt,
                        "bsfuji-subchannel",
                        genreCode,
                        GenreName(genreCode)));
                }
            }
        }

        return programs
            .GroupBy(program => (program.Title, program.StartAt))
            .Select(group => group.First())
            .OrderBy(program => program.StartAt)
            .ToList();
    }

    private List<EpgProgram> ParseAtxPrograms(string html)
    {
        var weekStart = ParseAtxWeekStart(html);
        if (weekStart == null)
        {
            _logger.LogDebug("[ProgramInfo] AT-X 番組表の週開始日を解析できませんでした");
            return new List<EpgProgram>();
        }

        var tableBody = ExtractAtxTimeTableBody(html);
        if (tableBody == null)
        {
            _logger.LogDebug("[ProgramInfo] AT-X 番組表の timeTable を解析できませんでした");
            return new List<EpgProgram>();
        }

        var rows = Regex.Matches(tableBody, @"<tr[^>]*>(?<row>.*?)</tr>",
            RegexOptions.Singleline | RegexOptions.IgnoreCase);
        var rowSpans = new int[7];
        var byDay = Enumerable.Range(0, 7).Select(_ => new List<AtxProgramStart>()).ToArray();

        foreach (Match rowMatch in rows)
        {
            var row = rowMatch.Groups["row"].Value;
            var timeMatch = Regex.Match(row, @"<th[^>]*class=""[^""]*bgYellow[^""]*""[^>]*>\s*(?<time>\d{1,2}:\d{2})\s*</th>",
                RegexOptions.Singleline | RegexOptions.IgnoreCase);
            if (!timeMatch.Success || !TryParseAtxTime(timeMatch.Groups["time"].Value, out var hour, out var minute))
                continue;

            var cells = Regex.Matches(row, @"<td(?<attrs>[^>]*)>(?<cell>.*?)</td>",
                RegexOptions.Singleline | RegexOptions.IgnoreCase).Cast<Match>().ToArray();
            var cellIndex = 0;

            for (var day = 0; day < 7; day++)
            {
                if (rowSpans[day] > 0)
                {
                    rowSpans[day]--;
                    continue;
                }

                if (cellIndex >= cells.Length)
                    break;

                var cell = cells[cellIndex++];
                var attrs = cell.Groups["attrs"].Value;
                var rowspan = 1;
                var rowspanMatch = Regex.Match(attrs, @"rowspan=""(?<rowspan>\d+)""", RegexOptions.IgnoreCase);
                if (rowspanMatch.Success && int.TryParse(rowspanMatch.Groups["rowspan"].Value, out var parsedRowspan))
                    rowspan = Math.Max(1, parsedRowspan);
                rowSpans[day] = rowspan - 1;

                var titleMatch = Regex.Match(cell.Groups["cell"].Value, @"<a\b[^>]*>(?<title>.*?)</a>",
                    RegexOptions.Singleline | RegexOptions.IgnoreCase);
                if (!titleMatch.Success)
                    continue;

                var title = FormatAtxTitle(
                    WebUtility.HtmlDecode(Regex.Replace(titleMatch.Groups["title"].Value, "<.*?>", "")),
                    attrs);
                if (string.IsNullOrWhiteSpace(title))
                    continue;

                byDay[day].Add(new AtxProgramStart(CreateAtxStartTime(weekStart.Value.AddDays(day), hour, minute), title));
            }
        }

        var programs = new List<EpgProgram>();
        for (var day = 0; day < byDay.Length; day++)
        {
            var dayPrograms = byDay[day];
            var ordered = dayPrograms.OrderBy(program => program.StartAt).ToArray();
            for (var i = 0; i < ordered.Length; i++)
            {
                var startAt = ordered[i].StartAt;
                var endAt = i + 1 < ordered.Length
                    ? ordered[i + 1].StartAt
                    : CreateAtxStartTime(weekStart.Value.AddDays(day), 30, 0);
                if (endAt > startAt)
                    programs.Add(new EpgProgram(ordered[i].Title, startAt, endAt, "atx", null, null));
            }
        }

        return programs.OrderBy(program => program.StartAt).ToList();
    }

    private static string? ExtractAtxTimeTableBody(string html)
    {
        var tableStart = Regex.Match(html, @"<table\b[^>]*\bid=""timeTable""[^>]*>",
            RegexOptions.Singleline | RegexOptions.IgnoreCase);
        if (!tableStart.Success)
            return null;

        var bodyStart = tableStart.Index + tableStart.Length;
        var tableEnd = html.IndexOf("</table>", bodyStart, StringComparison.OrdinalIgnoreCase);
        if (tableEnd < 0)
            return null;

        var table = html.Substring(bodyStart, tableEnd - bodyStart);
        var bodyMatch = Regex.Match(table, @"<tbody[^>]*>(?<body>.*)</tbody>",
            RegexOptions.Singleline | RegexOptions.IgnoreCase);
        return bodyMatch.Success ? bodyMatch.Groups["body"].Value : table;
    }

    private static string FormatAtxTitle(string title, string cellAttrs)
    {
        title = Regex.Replace(NormalizeTitle(title), @"\s*▲\s*$", "[字]");
        var prefix = "";
        if (HasAtxCellClass(cellAttrs, "bgPink")) prefix += "[新]";
        if (HasAtxCellClass(cellAttrs, "bgBlue")) prefix += "[終]";
        return $"{prefix}{title}";
    }

    private static string FormatAtxApiTitle(string title, string episode, int broadcastType)
    {
        var text = string.IsNullOrWhiteSpace(episode)
            ? title
            : $"{title} {episode}";
        text = Regex.Replace(NormalizeTitle(text), @"\s*▲\s*$", "[字]");
        var prefix = broadcastType switch
        {
            1 => "[新]",
            3 => "[終]",
            _ => "",
        };
        return $"{prefix}{text}";
    }

    private static bool HasAtxCellClass(string attrs, string className)
    {
        var classMatch = Regex.Match(attrs, @"\bclass\s*=\s*""(?<class>[^""]*)""",
            RegexOptions.IgnoreCase);
        return classMatch.Success &&
            classMatch.Groups["class"].Value.Split(' ', StringSplitOptions.RemoveEmptyEntries)
                .Any(value => string.Equals(value, className, StringComparison.OrdinalIgnoreCase));
    }

    private DateOnly? ParseAtxWeekStart(string html)
    {
        var match = Regex.Match(html, @"週間番組表\((?<year>\d{4})/(?<month>\d{1,2})/(?<day>\d{1,2})～",
            RegexOptions.CultureInvariant);
        if (!match.Success)
            return null;
        return new DateOnly(
            int.Parse(match.Groups["year"].Value),
            int.Parse(match.Groups["month"].Value),
            int.Parse(match.Groups["day"].Value));
    }

    private static bool TryParseAtxTime(string text, out int hour, out int minute)
    {
        var parts = text.Split(':', 2);
        if (parts.Length == 2 &&
            int.TryParse(parts[0], out hour) &&
            int.TryParse(parts[1], out minute))
            return true;

        hour = 0;
        minute = 0;
        return false;
    }

    private static bool TryParseCompactTime(string text, out int hour, out int minute)
    {
        if (text.Length == 4 &&
            int.TryParse(text[..2], out hour) &&
            int.TryParse(text[2..], out minute))
            return true;

        hour = 0;
        minute = 0;
        return false;
    }

    private DateTimeOffset CreateAtxStartTime(DateOnly date, int hour, int minute)
    {
        while (hour >= 24)
        {
            date = date.AddDays(1);
            hour -= 24;
        }

        var local = date.ToDateTime(new TimeOnly(hour, minute));
        return new DateTimeOffset(local, _timeZone.GetUtcOffset(local));
    }

    private static string GetStringProperty(JsonElement element, params string[] names)
    {
        foreach (var name in names)
        {
            if (element.TryGetProperty(name, out var value))
                return value.GetString() ?? "";
        }
        return "";
    }

    private static bool TryParseDateTimeOffsetProperty(JsonElement element, out DateTimeOffset value,
        params string[] names)
    {
        foreach (var name in names)
        {
            if (element.TryGetProperty(name, out var property) &&
                DateTimeOffset.TryParse(property.GetString(), out value))
                return true;
        }

        value = default;
        return false;
    }

    private static string? GetNhkGenreCode(JsonElement program)
    {
        foreach (var genres in EnumerateNhkGenreArrays(program))
        {
            foreach (var genre in genres.EnumerateArray())
            {
                var id = GetStringProperty(genre, "id");
                if (id.Length < 2)
                    continue;
                if (int.TryParse(id[..2], out var major) && major is >= 0 and <= 15)
                    return $"0x{major:X}";
            }
        }

        return null;
    }

    private bool TryParseOujDateTime(string? dateText, string? timeText, out DateTimeOffset value)
    {
        value = default;
        if (string.IsNullOrWhiteSpace(dateText) || string.IsNullOrWhiteSpace(timeText))
            return false;
        if (!DateOnly.TryParse(dateText.Trim(), out var date))
            return false;

        var parts = timeText.Trim().Split(':', 2);
        if (parts.Length != 2 ||
            !int.TryParse(parts[0], out var hour) ||
            !int.TryParse(parts[1], out var minute) ||
            hour < 0 || minute is < 0 or > 59)
            return false;

        var dayOffset = hour / 24;
        hour %= 24;
        var local = date.AddDays(dayOffset).ToDateTime(new TimeOnly(hour, minute));
        value = new DateTimeOffset(local, _timeZone.GetUtcOffset(local));
        return true;
    }

    private static IEnumerable<JsonElement> EnumerateNhkGenreArrays(JsonElement program)
    {
        if (program.TryGetProperty("genre", out var directGenre) &&
            directGenre.ValueKind == JsonValueKind.Array)
            yield return directGenre;

        if (program.TryGetProperty("identifierGroup", out var identifierGroup) &&
            identifierGroup.TryGetProperty("genre", out var identifierGroupGenre) &&
            identifierGroupGenre.ValueKind == JsonValueKind.Array)
            yield return identifierGroupGenre;

        if (program.TryGetProperty("about", out var about) &&
            about.TryGetProperty("genre", out var aboutGenre) &&
            aboutGenre.ValueKind == JsonValueKind.Array)
            yield return aboutGenre;
    }

    private bool EvaluateCurrentPrograms(DateTimeOffset nowUtc)
    {
        var changed = !_hasBroadcastSnapshot;
        var now = TimeZoneInfo.ConvertTime(nowUtc, _timeZone);
        var nextPrograms = new Dictionary<string, ProgramInfo>();
        var staleAfter = TimeSpan.FromSeconds(Math.Max(60,
            _config.GetValue<int>("CacheServer:ProgramInfoStaleAfterSeconds", 3600)));
        var dropAfter = TimeSpan.FromSeconds(Math.Max(300,
            _config.GetValue<int>("CacheServer:ProgramInfoDropAfterSeconds", 86400)));

        lock (_lock)
        {
            // 内部フェッチ（TVer/NHK等）が長時間失敗・停止していても、EDCBアップローダー等の
            // 外部インポートが継続していれば現在番組の評価を止めない。どちらか新しい方を採用する。
            var lastDataUtc = _lastFetchUtc > _lastImportUtc ? _lastFetchUtc : _lastImportUtc;
            var dataAge = lastDataUtc == DateTimeOffset.MinValue
                ? TimeSpan.MaxValue
                : nowUtc - lastDataUtc;
            // 取得から極端に時間が経過した EPG はそもそも信用しない
            if (dataAge > dropAfter)
            {
                if (_currentPrograms.Count > 0)
                {
                    _currentPrograms.Clear();
                    changed = true;
                }
                return changed;
            }
            var dataIsStale = dataAge > staleAfter;

            foreach (var info in _channelCatalog.All)
            {
                if (!_epgPrograms.TryGetValue(info.Video, out var programs))
                    continue;

                var current = programs.FirstOrDefault(program => program.StartAt <= now && now < program.EndAt);
                if (current == null) continue;

                var next = new ProgramInfo(current.Title, current.StartAt, current.EndAt,
                    current.Source, current.GenreCode, current.GenreName, FormatServerTime(), dataIsStale);
                nextPrograms[info.Video] = next;
            }

            ApplyCurrentProgramFallback(nextPrograms, "jk102", "jk101");
            ApplyCurrentProgramFallback(nextPrograms, "jk232", "jk231");

            foreach (var (video, next) in nextPrograms)
            {
                if (!_currentPrograms.TryGetValue(video, out var existing) ||
                    existing.Title != next.Title ||
                    existing.StartAt != next.StartAt ||
                    existing.EndAt != next.EndAt ||
                    existing.Stale != next.Stale)
                    changed = true;
            }

            foreach (var removed in _currentPrograms.Keys.Except(nextPrograms.Keys).ToArray())
            {
                _currentPrograms.Remove(removed);
                changed = true;
            }
            foreach (var (video, program) in nextPrograms)
                _currentPrograms[video] = program;
        }

        return changed;
    }

    private static void ApplyCurrentProgramFallback(Dictionary<string, ProgramInfo> programs,
        string targetVideo, string fallbackVideo)
    {
        if (programs.ContainsKey(targetVideo))
            return;
        if (programs.TryGetValue(fallbackVideo, out var fallback))
            programs[targetVideo] = fallback;
    }

    private static IReadOnlyList<EpgProgram> ResolveSchedulePrograms(
        IReadOnlyDictionary<string, List<EpgProgram>> epgPrograms,
        string video)
    {
        if (epgPrograms.TryGetValue(video, out var programs))
            return programs;

        if (video == "jk102" && epgPrograms.TryGetValue("jk101", out var nhkBsPrograms))
            return nhkBsPrograms;

        return Array.Empty<EpgProgram>();
    }

    private void MarkCurrentProgramsStale()
    {
        lock (_lock)
        {
            foreach (var (video, program) in _currentPrograms.ToArray())
                _currentPrograms[video] = program with { Stale = true, UpdatedAt = FormatServerTime() };
        }
    }

    private DateOnly GetBroadcastDate(DateTimeOffset utcNow)
    {
        var localNow = TimeZoneInfo.ConvertTime(utcNow, _timeZone);
        var date = DateOnly.FromDateTime(localNow.DateTime);
        return localNow.Hour < 5 ? date.AddDays(-1) : date;
    }

    private static bool IsTimeInWindow(TimeOnly time, TimeOnly start, TimeOnly end)
    {
        if (start == end)
            return false;
        return start < end
            ? start <= time && time < end
            : time >= start || time < end;
    }

    private DateTimeOffset CreateBroadcastBoundary(DateOnly date)
    {
        var local = date.ToDateTime(new TimeOnly(5, 0));
        return new DateTimeOffset(local, _timeZone.GetUtcOffset(local));
    }

    private string FormatServerTime() =>
        TimeZoneInfo.ConvertTime(DateTimeOffset.UtcNow, _timeZone).ToString("yyyy-MM-ddTHH:mm:ss.fffzzz");

    private static string FormatTitle(string title, JsonElement program)
    {
        title = NormalizeTitle(title);
        var prefix = "";
        if (program.TryGetProperty("icon", out var icon))
        {
            if (GetIconFlag(icon, "new")) prefix += "[新]";
            if (GetIconFlag(icon, "revival")) prefix += "[再]";
            if (GetIconFlag(icon, "last")) prefix += "[終]";
        }
        return $"{prefix}{title}";
    }

    private static bool GetIconFlag(JsonElement icon, string name) =>
        icon.TryGetProperty(name, out var value) &&
        value.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.Number => value.TryGetInt32(out var i) && i != 0,
            JsonValueKind.String => bool.TryParse(value.GetString(), out var b) ? b :
                value.GetString() == "1",
            _ => false,
        };

    private static string NormalizeTitle(string title) =>
        Regex.Replace(title.Replace("\r", "").Replace("\n", " ").Trim(), @"\s+", " ");

    private static string ExtractHtmlText(string html, string className)
    {
        var match = Regex.Match(html,
            $@"<span\b[^>]*class=""[^""]*\b{Regex.Escape(className)}\b[^""]*""[^>]*>(?<text>.*?)</span>",
            RegexOptions.Singleline | RegexOptions.IgnoreCase);
        return match.Success
            ? WebUtility.HtmlDecode(Regex.Replace(match.Groups["text"].Value, "<.*?>", " ")).Trim()
            : "";
    }

    private static string? NormalizeGenreCode(string genre)
    {
        if (string.IsNullOrWhiteSpace(genre))
            return null;
        genre = genre.Trim();
        return genre.StartsWith("0x", StringComparison.OrdinalIgnoreCase)
            ? "0x" + genre[2..].ToUpperInvariant()
            : genre.ToUpperInvariant();
    }

    private static string? GenreName(string? genreCode) => genreCode switch
    {
        "0x0" => "ニュース／報道",
        "0x1" => "スポーツ",
        "0x2" => "情報／ワイドショー",
        "0x3" => "ドラマ",
        "0x4" => "音楽",
        "0x5" => "バラエティ",
        "0x6" => "映画",
        "0x7" => "アニメ／特撮",
        "0x8" => "ドキュメンタリー／教養",
        "0x9" => "劇場／公演",
        "0xA" => "趣味／教育",
        "0xB" => "福祉",
        "0xF" => "その他",
        _ => null,
    };

    private string? GenreCodeFromBs4Category(string category) => category switch
    {
        "ニュース" or "報道・情報" => "0x0",
        "スポーツ" => "0x1",
        "情報" => "0x2",
        "ドラマ" => "0x3",
        "音楽" => "0x4",
        "バラエティ" => "0x5",
        "映画" => "0x6",
        "アニメ" or "特撮" => "0x7",
        "ドキュメンタリー" or "紀行ドキュメンタリー" => "0x8",
        "趣味" or "教育" => "0xA",
        _ => null,
    };

    private string? GenreCodeFromBsFujiCategory(string categoryName, string categoryCode)
    {
        categoryName = categoryName.Trim();
        categoryCode = categoryCode.Trim().ToLowerInvariant();

        if (!string.IsNullOrWhiteSpace(categoryName))
        {
            var code = categoryName switch
            {
                "報道・情報" or "ニュース" => "0x0",
                "スポーツ" => "0x1",
                "情報" or "ワイドショー" => "0x2",
                "ドラマ" => "0x3",
                "音楽" => "0x4",
                "バラエティ" => "0x5",
                "映画" => "0x6",
                "アニメ・キッズ" or "アニメ" or "特撮" => "0x7",
                "ドキュメンタリー・教養" or "ドキュメンタリー" or "教養" => "0x8",
                "趣味・教育" or "趣味" or "教育" => "0xA",
                _ => null,
            };
            if (code != null)
                return code;
        }

        return categoryCode switch
        {
            "news" => "0x0",
            "sports" => "0x1",
            "info" => "0x2",
            "drama" => "0x3",
            "music" => "0x4",
            "variety" => "0x5",
            "movie" => "0x6",
            "anime" or "kids" => "0x7",
            "documentary" or "culture" => "0x8",
            "education" => "0xA",
            _ => null,
        };
    }

    private DateTimeOffset CreateBs4StartTime(DateOnly date, int hour, int minute)
    {
        if (hour < 4)
            date = date.AddDays(1);
        while (hour >= 24)
        {
            date = date.AddDays(1);
            hour -= 24;
        }

        var local = date.ToDateTime(new TimeOnly(hour, minute));
        return new DateTimeOffset(local, _timeZone.GetUtcOffset(local));
    }

    private DateTimeOffset CreateBs4BroadcastBoundary(DateOnly date)
    {
        var local = date.ToDateTime(new TimeOnly(4, 0));
        return new DateTimeOffset(local, _timeZone.GetUtcOffset(local));
    }

    private DateTimeOffset CreateBsFujiStartTime(DateOnly date, int hour, int minute)
    {
        if (hour < 5)
            date = date.AddDays(1);
        while (hour >= 24)
        {
            date = date.AddDays(1);
            hour -= 24;
        }

        var local = date.ToDateTime(new TimeOnly(hour, minute));
        return new DateTimeOffset(local, _timeZone.GetUtcOffset(local));
    }

    private static string TruncateLogBody(string body)
    {
        body = NormalizeTitle(body);
        return body.Length <= 1000 ? body : body[..1000] + "...";
    }

    private static string RedactOujUrl(string url) => url;

    private static string GetJsonKeys(JsonElement element)
    {
        if (element.ValueKind != JsonValueKind.Object)
            return element.ValueKind.ToString();
        return string.Join(",", element.EnumerateObject().Select(property => property.Name));
    }

    public static object? ToApiProgram(ProgramInfo? program) => program == null ? null : new
    {
        title = program.Title,
        startAt = program.StartAt.ToString("yyyy-MM-ddTHH:mm:sszzz"),
        endAt = program.EndAt.ToString("yyyy-MM-ddTHH:mm:sszzz"),
        source = program.Source,
        genreCode = program.GenreCode,
        genreName = program.GenreName,
        updatedAt = program.UpdatedAt,
        stale = program.Stale,
    };

    private static object ToApiEpgProgram(EpgProgram program) => new
    {
        title = program.Title,
        startAt = program.StartAt.ToString("yyyy-MM-ddTHH:mm:sszzz"),
        endAt = program.EndAt.ToString("yyyy-MM-ddTHH:mm:sszzz"),
        source = program.Source,
        genreCode = program.GenreCode,
        genreName = program.GenreName,
    };

    private static TimeZoneInfo ResolveTimeZone(string timeZoneId)
    {
        try { return TimeZoneInfo.FindSystemTimeZoneById(timeZoneId); }
        catch { return TimeZoneInfo.Local; }
    }

    private sealed record TVerBroadcasterInfo(string Type, int Area, int BroadcasterId);
    private sealed record AtxProgramStart(DateTimeOffset StartAt, string Title);
}

public sealed record ProgramInfo(
    string Title,
    DateTimeOffset StartAt,
    DateTimeOffset EndAt,
    string Source,
    string? GenreCode,
    string? GenreName,
    string UpdatedAt,
    bool Stale);

public sealed record EpgProgram(
    string Title,
    DateTimeOffset StartAt,
    DateTimeOffset EndAt,
    string Source,
    string? GenreCode,
    string? GenreName);
