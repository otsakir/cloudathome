## About

A system that allows running application servers at home and access them from the internet.


## Overview

### Sites

* A `cloud server` running on any of the typical cloud providers. It is the entry point to the system for all https requests.
* A network of hosts behind NAT typically running at home. This is the `home network`

### Components

* **Cloud Proxy** - Main entry point to the system. It consists of a HAproxy application that listens on port 443 of the cloud server. It can be dynamically configured to 'forward' requests to local ports based on the request domain name (SNI). 

* **ProxyAgent** - An agent-like web service running on the cloud server that dynamically controls Cloud Proxy. It adds/removes forwarding mappings on demand. It offers a REST api to do that.

* **HomeGateway** - A linux machine plugged to the home network (behind NAT(s)) that represents the owner of the system and services and controls the overall operation of the system. It makes forwarding requests to the ProxyAgent running on the cloud server.  It sets up ssh tunnels from the cloud server to the home network. It contains a web app with UI to manage the system.


## API

The ProxyAgent REST API is browsable via Swagger UI when running in debug mode:

- Swagger UI: `http://localhost:8000/api/schema/swagger/`
- ReDoc: `http://localhost:8000/api/schema/redoc/`
- OpenAPI schema (JSON): `http://localhost:8000/api/schema/`


## Setting up a tunnel (walkthrough)

This walkthrough uses `localhost` as the cloud server address (i.e. the stack is running locally via Docker Compose). Replace it with your actual cloud server hostname for a real deployment.

### 1. Register a home

POST to `/api/homes/` while logged in as `alice`, passing your SSH public key. Make sure to pass
proper authentication headers, `sessionid` etc. accordingly:

```bash
PKEY=$(cat ~/.ssh/id_rsa.pub)
curl -s -X POST http://localhost:8000/api/homes/ \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"public_key": "'$PKEY'"}'
```

The response contains everything needed to connect:

```json
{
  "name": "alice",
  "ssh_username": "home00_alice",
  "port_base": 2000,
  "port_count": 10
}
```

### 2. Open the reverse SSH tunnel

From the home machine, forward a port on the cloud server back to a local port. Use `port_base` from the response as the remote port:

```bash
ssh -N -T -R 127.0.0.1:2000:127.0.0.1:2600 home00_alice@localhost -p 8022
```

This maps **port 2000 on the cloud server** → **port 2600 on the home machine**. The connection will appear to hang — that is correct; it is holding the tunnel open.

### 3. Start a listener on the home machine

In a separate terminal, start a netcat listener on the local port used above (2600):

```bash
nc -l -p 2600
```

### 4. Send a request through the tunnel

From the cloud server (or any machine with access to it), connect to the tunnel port:

```bash
curl http://localhost:2000
```

The request travels through the SSH tunnel and arrives at the `nc` listener on the home machine. Anything typed into the `nc` terminal is sent back as the response.





