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

### How it works

  1. A home server registers with the cloud via a REST API, providing an SSH public key.
  2. The cloud creates a dedicated system user and SSH tunnel endpoint for that home.
  3. The home's gateway establishes an SSH reverse tunnel to the cloud server on an assigned port.
  4. The home creates a proxy mapping (hostname → tunnel port), which the cloud writes into HAProxy's SNI map at runtime.
  5. Incoming HTTPS traffic hits HAProxy on port 443, which routes it by SNI hostname through the tunnel to the home server — no cloud-side firewall changes, no reload needed.


## API

The ProxyAgent REST API is browsable via Swagger UI when running in debug mode:

- Swagger UI: `http://localhost:8000/api/schema/swagger/`
- ReDoc: `http://localhost:8000/api/schema/redoc/`
- OpenAPI schema (JSON): `http://localhost:8000/api/schema/`
- DRF login: http://localhost:8000/api-auth/login/


## Setting up a tunnel (walkthrough)

This walkthrough uses `localhost` as the cloud server address (i.e. the stack is running locally via Docker Compose). Replace it with your actual cloud server hostname for a real deployment.

### 1. Create a user

The actual process to create a user for the cloudserver platform is not yet settled. We're assuming that you have a plain django user named `alice`.

### 2. Register a home

POST to `/api/homes/` while logged in as `alice`, passing your SSH public key to the body. Make sure to pass
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

### 3. Open the reverse SSH tunnel

From the home machine initiate a reverse port forwarding command. Map an internal port on the cloud server back to a 
`host:port` at the local network of the home machine. Use `port_base` from the response of the previous step as the 
remote port:

```bash
ssh -N -T -R 127.0.0.1:2000:127.0.0.1:2600 home00_alice@localhost -p 8022
```

This maps **port 2000 on the cloud server** → **port 2600 on the home machine**. The connection will appear to hang — that is correct; it is holding the tunnel open.

### 4. Create a proxy mapping 

Next, you need to create a proxy mapping. This entails creating the django `proxy-mapping` entity and the respective
state in _haproxy_. Again, make sure you provide authorization information as this is a user-scoped operation.

```
    POST /api/proxy-mappings/ {
      "host": "localhost",
      "local_port": 200,
      "scheme": "https",
      "home": 1
    }
```

### 5. Start a listening server 

At your home machine, in a separate terminal, start a netcat listener on the local port used above (2600):

```bash
nc -l -p 2600
```

### 6. Make a request through the tunnel

From the cloud server (or any machine with access to it), connect to the tunnel port:

```bash
curl https://localhost
```

The request reaches haproxy, is reverse proxied to the internal port where the SSH tunnel 
listens to, it travels through the SSH tunnel and arrives at the `nc` listener at the home machine. Anything typed
into the `nc` terminal is sent back as the response.





