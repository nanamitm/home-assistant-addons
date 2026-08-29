namespace jkcnsl_cache;

// ProgramInfoService originally notifies jkcnsl-cache's comment client over a
// WebSocket. The EPG-only app has no push clients, so this boundary is a no-op.
public sealed class ChannelsStreamBroadcaster
{
    public Task BroadcastAsync(object payload, CancellationToken cancellationToken) =>
        Task.CompletedTask;
}
