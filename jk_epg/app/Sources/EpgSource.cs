namespace jkcnsl_cache.Sources;

public interface IEpgSource
{
    string Key { get; }
    string Name { get; }
    string ConfigSection { get; }
    bool IsEnabled(IConfiguration config);
}

public abstract class EpgSource(string key, string name, string configSection) : IEpgSource
{
    public string Key { get; } = key;
    public string Name { get; } = name;
    public string ConfigSection { get; } = configSection;

    public virtual bool IsEnabled(IConfiguration config) =>
        config.GetValue<bool>($"{ConfigSection}:Enabled", true);
}

public sealed class TVerEpgSource() : EpgSource("tver", "TVer", "CacheServer:TVerProgram")
{
    public override bool IsEnabled(IConfiguration config) => true;
}

public sealed class NhkEpgSource() : EpgSource("nhk", "NHK番組API", "CacheServer:NhkProgramApi")
{
    public override bool IsEnabled(IConfiguration config) =>
        !string.IsNullOrWhiteSpace(config[$"{ConfigSection}:API_Key"] ?? config[$"{ConfigSection}:ApiKey"]);
}

public sealed class AtxEpgSource() : EpgSource("atx", "AT-X", "CacheServer:AtxProgram");

public sealed class OujEpgSource() : EpgSource("ouj", "放送大学", "CacheServer:OujProgram");

public sealed class Bs4SubChannelEpgSource()
    : EpgSource("bs4", "BS日テレサブ", "CacheServer:Bs4SubChannelProgram");

public sealed class BsTbsSubChannelEpgSource()
    : EpgSource("bstbs", "BS-TBSサブ", "CacheServer:BsTbsSubChannelProgram");

public sealed class BsFujiSubChannelEpgSource()
    : EpgSource("bsfuji", "BSフジサブ", "CacheServer:BsFujiSubChannelProgram");
