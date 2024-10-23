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

Below is running the controller module in both Linux and Python manually.

#### Linux
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