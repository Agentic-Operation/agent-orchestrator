# agent-orchestrator

Swarm/hierarchical control plane: loads Spec-443 §6.4 topology, validates members against Agent-Registry cards, wires Spec-444 §4 protocol handlers (a2a_jsonrpc/rep/wo_a/mcp), pub/sub coordination variables, conditional sensitivity signals, per-agent autonomy + individual/mesh-level outcome tracking.\n\nRun: `python src/orchestrator.py --port 8093 --registry http://localhost:8080`

Spec repos: agent-profile-management (Spec-443) · agent-bootstrap-management (Spec-444) · agent-discovery-card (Spec-445) · docs: agent-standard-docs · conformance: agent-conformance
License: Apache-2.0
