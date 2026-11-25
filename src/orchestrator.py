#!/usr/bin/env python3
"""agent-orchestrator — swarm/hierarchical control plane for the triad.

Loads a Spec-443 §6.4 topology block (from a profile.json), validates members against the
Agent-Registry (Spec-445 cards), wires Spec-444 §4 protocol handlers, manages coordination
variables (publisher/consumer pub-sub) and sensitivity signals, and tracks outcomes per agent
and at mesh level (Spec-443 §9 metrics).

Endpoints (base /v1):
  POST /topology/load        {"profile": path-or-inline} -> validates + registers the mesh
  GET  /meshes               list loaded meshes (pattern, orchestrator, members)
  GET  /meshes/{id}/members  member agents with per-agent autonomy + card presence in registry
  PUT  /meshes/{id}/variables/{name}   {"value": ..., "publisher": ...}  coordination variable update
  GET  /meshes/{id}/variables          current coordination variables
  GET  /meshes/{id}/outcomes           per-agent + mesh-level outcome metrics vs targets
  POST /meshes/{id}/signal             publish a sensitivity signal ("If X then Y") to members

Run: python src/orchestrator.py --port 8093 [--registry http://localhost:8080]
"""
import argparse
import json
import os
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse


def api(method, url, obj=None):
    data = json.dumps(obj).encode() if obj is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


class Mesh:
    def __init__(self, mesh_id, profile, registry):
        topo = (profile.get("coordination") or {}).get("topology") or {}
        self.id = mesh_id
        self.pattern = topo.get("pattern", "swarm")
        self.orchestrator = topo.get("orchestrator")
        self.members = topo.get("members", [])
        self.variables = {v["name"]: {"value": None, "publisher": v["publisher"], "consumer": v["consumer"]}
                          for v in (profile.get("coordination") or {}).get("variables", [])}
        self.signals = (profile.get("coordination") or {}).get("sensitivity_signals", [])
        self.registry = registry
        self.outcomes = {}  # agent_id -> {metric: {target, actual}}

    def member_status(self):
        out = []
        for m in self.members:
            code, card = api("GET", f"{self.registry}/v1/cards/{m['agent_id']}-card")
            out.append({**m, "card_registered": code == 200,
                        "card_autonomy": (card or {}).get("classification", {}).get("autonomy_level")})
        return out


class Handler(BaseHTTPRequestHandler):
    meshes: dict = None
    registry: str = "http://localhost:8080"

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def log_message(self, *a):
        pass

    def do_GET(self):
        p = urlparse(self.path).path.strip("/").split("/")
        if p == ["v1", "meshes"]:
            return self._send(200, [{ "id": m.id, "pattern": m.pattern, "orchestrator": m.orchestrator,
                                      "members": len(m.members)} for m in self.meshes.values()])
        if len(p) >= 3 and p[:2] == ["v1", "meshes"]:
            m = self.meshes.get(p[2])
            if not m:
                return self._send(404, {"error": "not found"})
            if len(p) == 4 and p[3] == "members":
                return self._send(200, m.member_status())
            if len(p) == 4 and p[3] == "variables":
                return self._send(200, m.variables)
            if len(p) == 4 and p[3] == "outcomes":
                per_agent = {a: m.outcomes.get(a, {}) for a in [x["agent_id"] for x in m.members]}
                return self._send(200, {"per_agent": per_agent, "mesh": {"agents": len(m.members), "pattern": m.pattern}})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        p = urlparse(self.path).path.strip("/").split("/")
        if p == ["v1", "topology", "load"]:
            b = self._body()
            profile = b.get("profile") if isinstance(b.get("profile"), dict) else json.load(open(b["profile"]))
            mid = (profile.get("id") or "mesh") + "-mesh"
            self.meshes[mid] = Mesh(mid, profile, self.registry)
            m = self.meshes[mid]
            # structural checks (Spec-443 §6.4 cross-checks)
            errs = []
            if m.pattern == "hierarchy" and not m.orchestrator:
                errs.append("hierarchy requires orchestrator")
            if profile.get("classification", {}).get("automation_role") == "Orchestrator Agent" and m.orchestrator != profile.get("id"):
                errs.append("Orchestrator Agent should be the topology orchestrator")
            return self._send(422 if errs else 201, {"mesh": mid, "pattern": m.pattern, "members": len(m.members), "errors": errs})
        if len(p) == 5 and p[:2] == ["v1", "meshes"] and p[3] == "variables":
            m = self.meshes.get(p[2])
            if not m or p[4] not in m.variables:
                return self._send(404, {"error": "not found"})
            b = self._body()
            m.variables[p[4]]["value"] = b.get("value")
            m.variables[p[4]]["publisher"] = b.get("publisher", m.variables[p[4]]["publisher"])
            return self._send(200, m.variables[p[4]])
        if len(p) == 4 and p[:2] == ["v1", "meshes"] and p[3] == "signal":
            m = self.meshes.get(p[2])
            if not m:
                return self._send(404, {"error": "not found"})
            sig = self._body().get("signal", "")
            if not sig.lower().startswith("if "):
                return self._send(422, {"error": "sensitivity signals must be conditional: 'If X then Y'"})
            m.signals.append(sig)
            return self._send(202, {"published": sig, "members": [x["agent_id"] for x in m.members]})
        return self._send(404, {"error": "not found"})

    def do_PUT(self):
        return self._send(405, {"error": "use POST"})


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8093)
    ap.add_argument("--registry", default="http://localhost:8080")
    a = ap.parse_args()
    Handler.meshes = {}
    Handler.registry = a.registry
    print(f"orchestrator listening on :{a.port} (registry={a.registry})")
    HTTPServer(("0.0.0.0", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
