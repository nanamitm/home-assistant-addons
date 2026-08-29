using jkcnsl_cache.Sources;
using Microsoft.Extensions.Configuration;

namespace JkEpg.Tests;

public sealed class EpgSourceTests
{
    [Fact]
    public void SourcesHaveStableUniqueKeys()
    {
        IEpgSource[] sources = [
            new TVerEpgSource(), new NhkEpgSource(), new AtxEpgSource(),
            new OujEpgSource(), new Bs4SubChannelEpgSource(),
            new BsTbsSubChannelEpgSource(), new BsFujiSubChannelEpgSource(),
        ];
        Assert.Equal(sources.Length, sources.Select(source => source.Key).Distinct().Count());
    }

    [Fact]
    public void NhkRequiresAnApiKeyAndOptionalSourcesHonorEnabled()
    {
        var config = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?>
        {
            ["CacheServer:NhkProgramApi:API_Key"] = "test-key",
            ["CacheServer:AtxProgram:Enabled"] = "false",
        }).Build();
        Assert.True(new NhkEpgSource().IsEnabled(config));
        Assert.False(new AtxEpgSource().IsEnabled(config));
        Assert.True(new TVerEpgSource().IsEnabled(config));
    }

    [Fact]
    public async Task MonitorExposesResponseShapeFailuresAndRecovers()
    {
        var monitor = new EpgSourceMonitor();
        await monitor.ObserveAsync("tver", () => Task.FromResult(false), () => 0);
        var failed = monitor.Get("tver");
        Assert.Equal(1, failed.ConsecutiveFailures);
        Assert.Equal("empty_or_invalid_response", failed.Error);

        await monitor.ObserveAsync("tver", () => Task.FromResult(true), () => 42);
        var recovered = monitor.Get("tver");
        Assert.Equal(0, recovered.ConsecutiveFailures);
        Assert.Equal(42, recovered.ItemCount);
        Assert.NotNull(recovered.LastSuccessAt);
    }
}
