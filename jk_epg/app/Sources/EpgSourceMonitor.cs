using System.Diagnostics;

namespace jkcnsl_cache.Sources;

public sealed record EpgSourceSnapshot(
    string Key,
    DateTimeOffset? LastAttemptAt,
    DateTimeOffset? LastSuccessAt,
    DateTimeOffset? LastFailureAt,
    long? DurationMs,
    int ItemCount,
    int ConsecutiveFailures,
    string? Error);

public sealed class EpgSourceMonitor
{
    private readonly object _lock = new();
    private readonly Dictionary<string, EpgSourceSnapshot> _snapshots = new(StringComparer.Ordinal);

    public async Task<bool> ObserveAsync(string key, Func<Task<bool>> operation, Func<int> itemCount)
    {
        var attemptedAt = DateTimeOffset.UtcNow;
        var timer = Stopwatch.StartNew();
        try
        {
            var success = await operation();
            Complete(key, attemptedAt, timer.ElapsedMilliseconds, success, itemCount(),
                success ? null : "empty_or_invalid_response");
            return success;
        }
        catch (OperationCanceledException) { throw; }
        catch (Exception error)
        {
            Complete(key, attemptedAt, timer.ElapsedMilliseconds, false, itemCount(), error.GetType().Name);
            throw;
        }
    }

    public EpgSourceSnapshot Get(string key)
    {
        lock (_lock)
            return _snapshots.TryGetValue(key, out var value)
                ? value
                : new(key, null, null, null, null, 0, 0, null);
    }

    private void Complete(string key, DateTimeOffset attemptedAt, long durationMs, bool success,
        int itemCount, string? error)
    {
        lock (_lock)
        {
            var previous = Get(key);
            _snapshots[key] = previous with
            {
                LastAttemptAt = attemptedAt,
                LastSuccessAt = success ? DateTimeOffset.UtcNow : previous.LastSuccessAt,
                LastFailureAt = success ? previous.LastFailureAt : DateTimeOffset.UtcNow,
                DurationMs = durationMs,
                ItemCount = itemCount,
                ConsecutiveFailures = success ? 0 : previous.ConsecutiveFailures + 1,
                Error = error,
            };
        }
    }
}
