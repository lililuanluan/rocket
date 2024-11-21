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


## Configuration files and running manually the Controller

This guide will show how to configure the
controller. This is useful as these are files
that you need to be aware of.


In case the `Rocket-packet-inteceptor` subrepository is empty, run the following commands:

```console

git submodule init

git submodule update --remote --merge

```

### Configure the application
The paragraphs below will aid in understanding the configuration files.

#### Change the Strategy
The strategy can be changed by editing the `xrpl_controller/__main__.py` file. It is as simple as importing the desired strategy, and passing the initialized Strategy class to the `serve` method. An example highlighting the initialization of the RandomFuzzer is seen below.

```python
from xrpl_controller.strategies import Strategy
from xrpl_controller.strategies.random_fuzzer import RandomFuzzer

from xrpl_controller.packet_server import serve

if __name__ == "__main__":
    strategy: Strategy = RandomFuzzer()
    serve(strategy)
```

#### Adjust the network configuration
The general configuration options of the validator node network can be changed in the `xrpl_controller/network_configs/default-network-config.yaml` file. Documentation on the various configuration options are included in the file.

#### Adjust the strategy configuration
The configuration options for the specified strategy (RandomFuzzer in this example) can be found under `xrpl_controller/strategies/configs/RandomFuzzer.yaml`.

### Running manually

Below is running the controller module in both Linux & macOS and Python manually.

#### Linux & macOS
```console
python -m venv .venv               # (optional) Create a virtual environment
source .venv/bin/activate          # (optional) Activate the environment
pip install -r requirements.txt    # Install requirements
python3 -m xrpl_controller         # Runs the application
```

#### Windows
```console
python -m venv .venv               # (optional) Create a virtual environment
./.venv/Scripts/activate           # (optional) Activate the environment
pip install -r requirements.txt    # Install requirements
python3 -m xrpl_controller         # Runs the application
```


## Useful Resources

- To contribute to the controller module read: 
[CONTRIBUTING.md](CONTRIBUTING.md)
- To run tests read:
[TESTING.md](TESTING.md)


