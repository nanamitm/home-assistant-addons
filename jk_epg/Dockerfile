FROM mcr.microsoft.com/dotnet/sdk:8.0-alpine AS build
WORKDIR /src
COPY app/JkEpg.csproj ./
RUN dotnet restore
COPY app/ ./
RUN dotnet publish -c Release -o /publish --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:8.0-alpine
RUN apk add --no-cache icu-data-full icu-libs jq tzdata
WORKDIR /app
COPY --from=build /publish/ ./
COPY custom_components/jk_epg /opt/jk_epg_custom_component
COPY run.sh /
RUN chmod a+x /run.sh
EXPOSE 8099
CMD ["/run.sh"]
