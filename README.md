# Rocket's controller module

This module is part of Rocket and is responsible for 
the mutating of messages that have been intercepted from 
the packet interceptor as well as attaching a particular action 
to the message. The interceptor is run as a subprocess in the controller.


## Pre-Requisites

- Python 3.12
- All pre-requisites of the [Rocket-packet-interceptor](https://gitlab.ewi.tudelft.nl/cse2000-software-project/2023-2024/cluster-q/13d/xrpl-packet-interceptor)
- The executable for the interceptor needs to be built in the submodule
- A compiled binary of the [Rocket-packet-interceptor](https://gitlab.ewi.tudelft.nl/cse2000-software-project/2023-2024/cluster-q/13d/xrpl-packet-interceptor)

## Useful Resources

- To contribute to the controller module read: 
[CONTRIBUTING.md](CONTRIBUTING.md)
- To run and configure the controller module application read:
[configuring-running.md](configuring-running.md)
- To run tests read:
[TESTING.md](TESTING.md)


