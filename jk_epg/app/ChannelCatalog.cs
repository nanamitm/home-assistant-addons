namespace jkcnsl_cache;

public sealed class ChannelCatalog
{
    private readonly IConfiguration _config;

    public ChannelCatalog(IConfiguration config)
    {
        _config = config;
    }

    public IReadOnlyList<ChannelInfo> All
    {
        get
        {
            var channels = ChannelList.All.ToDictionary(channel => channel.Video, StringComparer.Ordinal);

            foreach (var extra in _config.GetSection("CacheServer:ExtraChannels").GetChildren())
            {
                var channel = ReadChannelInfo(extra);
                if (channel != null)
                    channels[channel.Video] = channel;
            }

            foreach (var overrideSection in _config.GetSection("CacheServer:ChannelOverrides").GetChildren())
            {
                if (!channels.TryGetValue(overrideSection.Key, out var current))
                    continue;

                channels[overrideSection.Key] = current with
                {
                    Id = overrideSection.GetValue<int?>("Id") ?? current.Id,
                    Name = overrideSection.GetValue<string>("Name") ?? current.Name,
                    Video = overrideSection.GetValue<string>("Video") ?? current.Video,
                    Bs = overrideSection.GetValue<bool?>("Bs") ?? current.Bs,
                };
            }

            return channels.Values
                .OrderBy(channel => channel.Bs ? 1 : 0)
                .ThenBy(channel => channel.Id)
                .ToArray();
        }
    }

    private static ChannelInfo? ReadChannelInfo(IConfiguration section)
    {
        var id = section.GetValue<int?>("Id");
        var name = section.GetValue<string>("Name");
        var video = section.GetValue<string>("Video");
        var bs = section.GetValue<bool?>("Bs");

        if (id == null || string.IsNullOrWhiteSpace(name) || string.IsNullOrWhiteSpace(video) || bs == null)
            return null;

        return new ChannelInfo(id.Value, name, video, bs.Value);
    }
}
