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
}
