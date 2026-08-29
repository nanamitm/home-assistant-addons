using jkcnsl_cache;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;

namespace JkEpg.Tests;

public sealed class EpgStorageRecoveryTests
{
    [Fact]
    public async Task CorruptDatabaseIsQuarantinedAndRecreated()
    {
        var directory = Path.Combine(Path.GetTempPath(), $"jk-epg-{Guid.NewGuid():N}");
        Directory.CreateDirectory(directory);
        var database = Path.Combine(directory, "epg.db");
        await File.WriteAllTextAsync(database, "not a sqlite database");
        var config = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?>
        {
            ["EpgStorage:DbPath"] = database,
            ["EpgStorage:RetentionDays"] = "1",
        }).Build();
        var storage = new EpgStorageService(config, NullLogger<EpgStorageService>.Instance);

        await storage.StartAsync(CancellationToken.None);
        await storage.StopAsync(CancellationToken.None);

        Assert.NotNull(storage.LastRecovery);
        Assert.NotNull(storage.LastRecovery.BackupPath);
        Assert.True(File.Exists(storage.LastRecovery.BackupPath));
        Assert.Empty(storage.QueryPrograms(DateTimeOffset.UtcNow, DateTimeOffset.UtcNow.AddHours(1)));
        Directory.Delete(directory, recursive: true);
    }
}
