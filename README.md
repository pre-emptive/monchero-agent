# monchero-agent

The Monchero Monitoring Agent

Monchero is a monitoring platform, this repository is for the _agent_ which runs on
monitored Linux servers. The agent is responsible for collecting status and metrics
from the server it is running on and maintaining a 'state' for those services.

Monchero is modular, so it is possible to run an entire monitoring platform with
just the agent. However, it most situations it will be connected to a monitoring
server, to which it will submit metrics and status information for aggregation,
UI dashboards, centralised management, alerting and so on.

## About Monchero Agent

The Monchero Agent runs as a daemon on a server that needs to be monitored. It
periodically runs a series of _checks_ on that server. Those checks report system
features, providing a 'state' and optionally metrics for them. The agent then
maintains an aggregate state of all of those checks. If a check initially returns
'okay' for a given feature, but then returns 'warning', the Agent tracks this
change of state and can optionally perform actions (perhaps to remediate the
problem, or collect further information or to send a notification email, etc).

The agent can be configured to perform repeat checks before marking a feature
as 'bad'. For example, if a check returns something other than 'okay', the agent
can be made to wait for a few further checks to also be 'bad' before internally
changing the state of the feature (and subsequently running actions).

The agent provides a command line tool to briefly display the known state of
the system in the terminal. This means an operator working on the system can
check if their work has been distruptive, or if disruption has come to an end
without needing to use a central monitoring platform.

In future, the agent can be connected to a central monitoring plaform. This can be
either by a 'push' connection where the agent periodically submits information
to the server, or a 'pull' (poll) method where the server periodically requests
information from the client. This allows Monchero to work behind firewalls or
on private networks, with or without cloud access.

## Current State

Be an early adopter! Actually, Monchero Agent can be used to build a complete
single server monitoring platform. That is, it can periodically check services,
tracks their state and reports on them (on the command line). By using 'actions',
it's possible to have it send alerts (email, Slack, Telegram etc) too.

Things still to do:

- Implement a 'push' mechanism
- CI to build OS packages with the agent inside, proper versioning and strip the
  tests from the built installs. Include a suitable Systemd service unit.
- Documentation (lots of)

At that point, Monchero agent will be a reasonable 'MVP'. From them on, the high
level things that will need doing are:

- Implement a 'pull' mechanism. This needs some sort of certificate management
  solution with the poller
- Pull together a library of checks that can easily be added to any installation
