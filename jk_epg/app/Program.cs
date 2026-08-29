using System.Globalization;
using jkcnsl_cache;

var builder = WebApplication.CreateBuilder(args);
builder.Logging.AddSimpleConsole(options => options.TimestampFormat = "yyyy-MM-dd HH:mm:ss ");
builder.Services.AddSingleton<ChannelCatalog>();
builder.Services.AddSingleton<ChannelsStreamBroadcaster>();
builder.Services.AddSingleton<EpgStorageService>();
builder.Services.AddSingleton<ProgramInfoService>();
builder.Services.AddHostedService(sp => sp.GetRequiredService<EpgStorageService>());
builder.Services.AddHostedService(sp => sp.GetRequiredService<ProgramInfoService>());

var app = builder.Build();
app.UseDefaultFiles();
app.UseStaticFiles();

app.MapGet("/api/health", () => Results.Json(new { status = "ok" }));
app.MapGet("/api/programs/status", (ProgramInfoService programs) => Results.Json(programs.CreateStatusPayload()));
app.MapPost("/api/programs/refresh", async (HttpContext context, ProgramInfoService programs) =>
{
    try { return Results.Json(await programs.RefreshNowAsync(context.RequestAborted)); }
    catch (OperationCanceledException) { return Results.StatusCode(499); }
    catch (Exception error) { return Results.Problem(title: "EPG refresh failed", detail: error.Message); }
});

app.MapGet("/api/programs/current", (ProgramInfoService programs, ChannelCatalog catalog) =>
    Results.Json(new {
        updatedAt = DateTimeOffset.UtcNow,
        channels = catalog.All.Select(channel => new {
            channel.Id,
            channel.Video,
            channel.Name,
            channel.Bs,
            program = ProgramInfoService.ToApiProgram(programs.GetProgram(channel.Video)),
        }),
    }));

app.MapGet("/api/programs/schedule", (HttpContext context, ProgramInfoService programs) =>
{
    DateOnly? date = null;
    var value = context.Request.Query["date"].ToString();
    if (value.Length > 0)
    {
        if (!DateOnly.TryParseExact(value, "yyyy-MM-dd", CultureInfo.InvariantCulture,
                DateTimeStyles.None, out var parsed))
            return Results.BadRequest(new { error = "date must use yyyy-MM-dd format" });
        date = parsed;
    }
    return Results.Json(programs.CreateSchedulePayload(date));
});

app.MapGet("/api/programs/schedule/range", (EpgStorageService storage, IConfiguration config) =>
{
    var (earliest, latest) = storage.GetDateRange();
    if (earliest is null)
        return Results.Json(new { earliestDate = (string?)null, latestDate = (string?)null });

    TimeZoneInfo zone;
    try { zone = TimeZoneInfo.FindSystemTimeZoneById(config["CacheServer:BroadcastTimeZone"] ?? "Asia/Tokyo"); }
    catch { zone = TimeZoneInfo.Local; }
    static DateOnly BroadcastDate(DateTimeOffset value, TimeZoneInfo zone)
    {
        var local = TimeZoneInfo.ConvertTime(value, zone).AddHours(-5);
        return DateOnly.FromDateTime(local.DateTime);
    }
    return Results.Json(new {
        earliestDate = BroadcastDate(earliest.Value, zone).ToString("yyyy-MM-dd"),
        latestDate = BroadcastDate(latest!.Value, zone).ToString("yyyy-MM-dd"),
    });
});

app.MapFallbackToFile("index.html");
app.Run();
