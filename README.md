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





