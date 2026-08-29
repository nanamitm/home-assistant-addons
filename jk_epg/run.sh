#!/bin/sh
set -eu

options=/data/options.json
read_option() { jq -r ".${1}" "$options"; }

export ASPNETCORE_URLS=http://0.0.0.0:8099
export DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=false
export TZ="$(read_option timezone)"
export CacheServer__BroadcastTimeZone="$TZ"
export CacheServer__ProgramInfoUpdateIntervalSeconds="$(read_option update_interval)"
export CacheServer__NhkProgramApi__Area="$(read_option nhk_area)"
export CacheServer__NhkProgramApi__API_Key="$(read_option nhk_api_key)"
export CacheServer__AtxProgram__Enabled="$(read_option enable_atx)"
export CacheServer__OujProgram__Enabled="$(read_option enable_ouj)"
export CacheServer__Bs4SubChannelProgram__Enabled="$(read_option enable_subchannels)"
export CacheServer__BsTbsSubChannelProgram__Enabled="$(read_option enable_subchannels)"
export CacheServer__BsFujiSubChannelProgram__Enabled="$(read_option enable_subchannels)"
export EpgStorage__DbPath=/data/epg.db
export EpgStorage__RetentionDays="$(read_option retention_days)"

if [ "$(read_option install_ha_integration)" = "true" ]; then
  integration_dir=/homeassistant/custom_components/jk_epg
  mkdir -p "$integration_dir"
  cp -R /opt/jk_epg_custom_component/. "$integration_dir/"
  echo "JK EPG integration installed in $integration_dir"
fi

exec dotnet /app/JkEpg.dll
