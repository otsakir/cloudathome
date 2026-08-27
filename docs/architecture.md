# Architecture

## Components

| Component | Role |
|-----------|------|
| **HAProxy** | HTTPS ingress on port 443 (SNI-based routing) plus a configurable shared range of alternate HTTP/HTTPS ports, and TCP forwarding on ports 10000–10099 (port-based routing). Routes traffic to per-home SSH tunnel ports via runtime-updated map files. |
| **Django + sshd** | REST API and web UI for managing homes and proxy mappings. SSH server that accepts reverse tunnels from home networks. |

## Request & tunnel lifecycle

This is what happens end to end, across both repos, once a cloud server is up and a home has registered against it. None of these steps are things the cloud operator does by hand — they're the home operator's actions and the system's own behavior, described here so the rest of the docs make sense.

1. A home operator generates an API token from this cloud server's dashboard, then registers using `cloudathome-client` (generating a dedicated SSH key pair by default), which writes the resulting connection details to a local per-profile config file.
2. The home side starts its own Home Console for that profile. A single home client can hold several such profiles side by side — one per cloud server — each run as its own process, started independently.
3. For HTTP/HTTPS forwards, the home first registers one or more **base domains** with the cloud server (e.g. `mysite.example.com`). The cloud enforces that no two homes can claim overlapping domains. The home is then authoritative for that domain and all its subdomains.
4. The home adds forwards from its Home Console — either HTTP/HTTPS (domain-based) or TCP (port-based). Each forward registers a mapping directly in this cloud server's HAProxy (no persistent cloud-side state) and records the allocated tunnel port on the home side. HTTP/HTTPS forwards are only accepted if the hostname falls under one of the home's registered base domains. By default an HTTP/HTTPS forward publishes on the standard port (80/443); the home can instead request a port from this cloud's advertised alternate range (see [Custom HTTP/HTTPS inbound ports](features.md#custom-httphttps-inbound-ports)) — useful if the home's own network blocks outbound access to the standard ports, or it wants more than one independent entry point.
5. For HTTP/HTTPS forwards: the home opens the SSH tunnel and triggers certificate issuance locally. Certbot runs standalone on the home side; Let's Encrypt validates via the tunnel.
6. The home closes the temporary tunnel if needed, or keeps it open for production traffic.
7. Incoming HTTPS traffic hits this cloud server's HAProxy on port 443, routed by SNI hostname through the tunnel. Incoming TCP traffic hits HAProxy on the allocated public port (10000–10099), routed by destination port through the tunnel.
