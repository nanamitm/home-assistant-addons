namespace jkcnsl_cache.Sources;

public sealed class EpgSourceRegistry(IEnumerable<IEpgSource> sources)
{
    private readonly IReadOnlyDictionary<string, IEpgSource> _sources =
        sources.ToDictionary(source => source.Key, StringComparer.Ordinal);

    public IReadOnlyCollection<IEpgSource> All => _sources.Values;

    public IEpgSource this[string key] => _sources[key];
}

public static class EpgSourceServiceCollectionExtensions
{
    public static IServiceCollection AddEpgSources(this IServiceCollection services)
    {
        services.AddSingleton<IEpgSource, TVerEpgSource>();
        services.AddSingleton<IEpgSource, NhkEpgSource>();
        services.AddSingleton<IEpgSource, AtxEpgSource>();
        services.AddSingleton<IEpgSource, OujEpgSource>();
        services.AddSingleton<IEpgSource, Bs4SubChannelEpgSource>();
        services.AddSingleton<IEpgSource, BsTbsSubChannelEpgSource>();
        services.AddSingleton<IEpgSource, BsFujiSubChannelEpgSource>();
        services.AddSingleton<EpgSourceRegistry>();
        services.AddSingleton<EpgSourceMonitor>();
        return services;
    }
}
