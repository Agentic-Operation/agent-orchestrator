import json, subprocess, sys, time, urllib.request
from pathlib import Path
import pytest

SRV = Path(__file__).resolve().parents[1] / "src" / "orchestrator.py"
PROFILE = "/tmp/profile-example.json"

@pytest.fixture(scope="module")
def server():
    import urllib.request as u
    u.urlretrieve("https://raw.githubusercontent.com/Agentic-Operation/agent-profile-management/main/examples/loyalty-agent/profile.json", PROFILE)
    proc = subprocess.Popen([sys.executable, str(SRV), "--port", "8495", "--registry", "http://localhost:1"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    yield "http://localhost:8495"
    proc.terminate()

def post(url, obj):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(), headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req)

def test_load_topology_and_variables(server):
    r = post(f"{server}/v1/topology/load", {"profile": PROFILE})
    d = json.loads(r.read())
    assert r.status == 201 and d["pattern"] == "hierarchy" and d["members"] == 2
    mesh = d["mesh"]
    r = post(f"{server}/v1/meshes/{mesh}/variables/DAILY_REDEMPTION_BUDGET", {"value": 10000, "publisher": "campaign-orchestrator-agent-v1"})
    assert json.loads(r.read())["value"] == 10000
    import urllib.error
    with pytest.raises(urllib.error.HTTPError):
        post(f"{server}/v1/meshes/{mesh}/signal", {"signal": "I will optimize spend"})  # not conditional
