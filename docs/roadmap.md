# CloudAtHome Roadmap

Potential directions for extending the system. Items are grouped by theme, not strictly ordered.

---

## Access control & privacy

### IP allowlisting
Restrict which source IPs can reach a forwarded service. Configured per mapping in the Home Console. Implemented as HAProxy ACLs — no architectural change needed. Useful for services that only need to be accessible from known locations (office, family, VPN exit node).

### mTLS (client certificates)
Require connecting clients to present a certificate. HAProxy enforces this at the TLS handshake level before any data reaches the home. Services without built-in auth become inaccessible to anyone without the cert. Works for HTTPS and TCP forwards alike.

### Rate limiting
Per-source-IP connection and request limits enforced at HAProxy. Protects home services from abuse or accidental hammering without any home-side changes.

### Authentication proxy layer
An optional authentication gateway (e.g. Authelia, or a lightweight OIDC proxy) that sits between HAProxy and the SSH tunnel. Clients authenticate before reaching the home service. Works transparently for services with no built-in auth.

---

## Visibility & data ownership

### Per-home connection logs
Expose HAProxy connection metadata (source IPs, timestamps, bytes transferred) to the home operator via the Home Console. Currently only the cloud operator can see this. Gives homes visibility into who is accessing their services.

### Traffic stats per mapping
Bytes transferred and connection counts per forward, visible in the Home Console dashboard. Useful for understanding usage and detecting anomalies.

---

## IoT protocols

### MQTT — first-class support
MQTT over TCP already works via TCP forwarding, but deserves dedicated treatment given its dominance in home IoT (Home Assistant, Tasmota, ESPHome, Zigbee2MQTT):

- **Named MQTT forward type** in the UI — exposes MQTT-specific options rather than treating it as a generic TCP port
- **Topic-based access control** — restrict which MQTT topics are visible to remote clients, configured in the Home Console
- **Cloud-side MQTT bridge** — the cloud runs a lightweight MQTT broker that stays persistently connected to the home broker. Remote IoT devices connect to the cloud bridge; messages are relayed. Decouples remote clients from SSH tunnel availability.

### UDP tunneling
SSH reverse tunnels are TCP-only. Several important IoT and discovery protocols use UDP and are unsupported today:

- **CoAP** (port 5683) — the IoT equivalent of HTTP, widely used on constrained devices
- **mDNS / Bonjour** — used by HomeKit, Matter, Chromecast and most LAN-discovery protocols
- **SSDP** — UPnP device discovery
- **DTLS** — datagram TLS used by some CoAP implementations

Solving this requires either replacing SSH tunnels with **WireGuard** (preferred — also improves performance and reduces metadata exposure at the cloud) or a UDP-over-TCP shim layer.

### TURN server for WebRTC / cameras
IP cameras and audio/video IoT devices use WebRTC, which relies on UDP for media. Adding a TURN server at the cloud level would let cameras work with standard WebRTC clients without special tunneling. The cloud TURN server relays media between the camera (via the tunnel) and the remote viewer.

---

## Architectural improvements

### WireGuard relay
Replace SSH reverse tunnels with WireGuard. Benefits:
- **Privacy**: the cloud becomes a pure packet forwarder — no ability to inspect application-layer metadata
- **UDP support**: unlocks CoAP, mDNS, and all other UDP-based protocols
- **Performance**: lower overhead than SSH for sustained connections
- **Simplicity**: WireGuard configuration is simpler than per-user sshd rules

This is the most impactful single change but also the largest rewrite.

### Multi-cloud relay
Allow a home to register with more than one cloud server for redundancy or geographic distribution. Traffic is routed to whichever cloud endpoint is closest or available.
