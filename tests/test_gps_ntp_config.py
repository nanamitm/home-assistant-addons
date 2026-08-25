import json
import pathlib
import subprocess

import pytest
import yaml


ROOT = pathlib.Path(__file__).parents[1]
ADDON = ROOT / "gps_ntp"
RENDERER = ADDON / "rootfs/usr/local/bin/render-chrony-config"


def options(**overrides):
    value = yaml.safe_load((ADDON / "config.yaml").read_text())["options"]
    value.update(overrides)
    return value


def render(tmp_path, config):
    source = tmp_path / "options.json"
    target = tmp_path / "chrony.conf"
    source.write_text(json.dumps(config))
    subprocess.run([RENDERER, source, target], check=True)
    return target.read_text()


def test_addon_manifest():
    config = yaml.safe_load((ADDON / "config.yaml").read_text())
    assert config["slug"] == "gps_ntp"
    assert config["ports"]["123/udp"] == 123
    assert config["devices"] == ["/dev/pps0"]
    assert config["privileged"] == ["SYS_TIME"]


def test_renders_gpsd_shm_pps(tmp_path):
    result = render(tmp_path, options())
    assert "allow 192.168.0.0/16" in result
    assert "refclock SHM 0" in result
    assert "refclock SHM 1 refid PPS" in result


def test_renders_direct_pps(tmp_path):
    result = render(tmp_path, options(pps_via_gpsd=False))
    assert "refclock PPS /dev/pps0 refid PPS lock GPS" in result
    assert "refclock SHM 1" not in result


def test_rejects_invalid_network(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        render(tmp_path, options(allow_network="allow all"))
